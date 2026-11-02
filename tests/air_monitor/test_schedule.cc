#include <algorithm>
#include <array>
#include <vector>
#include "sensor_schedule.h"
#include "test_support.h"

using namespace air;
struct Transaction {
    SensorId sensor;
    uint16_t command;
    uint64_t time;
};
class FakeBus : public SensorBus {
public:
    bool Command(SensorId sensor, uint16_t command) override {
        writes.push_back({sensor, command, now});
        last[static_cast<size_t>(sensor)] = command;
        now += command_duration_ms;
        if (sensor == SensorId::Sfa40 && command == 0x00AC) {
            // The real sensor accepts start only while idle.
            if (sfa_running || now < sfa_idle_at)
                return false;
            sfa_running = true;
        }
        if (sensor == SensorId::Sfa40 && command == 0x50D2) {
            if (failed_stops > 0) {
                --failed_stops;
                return false;
            }
            sfa_running = false;
            sfa_idle_at = now + 25;
        }
        return !(sensor == SensorId::Sfa40 && command == 0xC0EB && !sfa_running && !idle_readable);
    }
    bool Receive(SensorId sensor, uint8_t* data, size_t size) override {
        if (sensor == SensorId::Sfa40) {
            if (!sfa_running && !idle_readable)
                return false;
            if (failed_reads > 0) {
                --failed_reads;
                return false;
            }
            const uint8_t frame[] = {0, 0x64, 0xFE, 0x72, 0xB0, 0xDC, 0x66, 0x66, 0x93, 0, 0, 0x81};
            CHECK(size == 12);
            std::copy(frame, frame + 12, data);
            const uint8_t status = sfa_running ? sfa_status : 3;
            if (status == 3) {
                data[0] = data[1] = 0;
                data[2] = 0x81;
            }
            const uint8_t status_crc[] = {0x81, 0x75, 0x58, 0xAC};
            data[9] = status;
            data[11] = status_crc[status];
            if (corrupt_reads > 0) {
                --corrupt_reads;
                data[2] ^= 1;
            }
            return true;
        }
        if (last[0] == 0x2313) {
            CHECK(size == 3);
            data[0] = 0;
            data[1] = 1;
            data[2] = 0xB0;
        } else if (last[0] == 0xE4B8) {
            CHECK(size == 3);
            data[0] = 0x80;
            data[1] = 1;
            data[2] = 0x93;
        } else {
            const uint8_t frame[] = {3, 0x60, 0x17, 0x66, 0x66, 0x93, 0x80, 0, 0xA2};
            CHECK(size == 9);
            std::copy(frame, frame + 9, data);
        }
        return true;
    }
    uint64_t now = 0;
    bool sfa_running = true;
    bool idle_readable = false;
    uint8_t sfa_status = 0;
    uint64_t sfa_idle_at = 0;
    uint64_t command_duration_ms = 0;
    unsigned failed_reads = 0, corrupt_reads = 0, failed_stops = 0;
    uint16_t last[2]{};
    std::vector<Transaction> writes;
};

void CheckSfaReadRecovery(bool corrupt_crc, bool lose_stop = false) {
    FakeBus bus;
    AirModel model;
    SensorSchedule schedule(bus, model);
    for (bus.now = 0; bus.now <= 2000; bus.now += 10)
        schedule.Tick(bus.now);
    CHECK(model.Snapshot(2000).hcho.has_value);
    // Three bad reads must not leave a running sensor stuck rejecting start forever.
    bus.failed_reads = corrupt_crc ? 0 : 3;
    bus.corrupt_reads = corrupt_crc ? 3 : 0;
    bus.failed_stops = lose_stop ? 1 : 0;
    for (; bus.now <= 20000; bus.now += 10)
        schedule.Tick(bus.now);
    const auto recovered = model.Snapshot(20000);
    CHECK(recovered.hcho.connected && recovered.hcho.has_value && !recovered.hcho.stale);
    CHECK(recovered.hcho.errors == 0);
    CHECK(recovered.hcho.last_value_ms > 15000);
    CHECK(recovered.co2.connected && !recovered.co2.stale);
    CHECK(recovered.co2.last_value_ms > 15000);
    NEAR(recovered.sfa.ppb, 10.f, .001f);
}

void CheckSfaWarmup() {
    FakeBus bus;
    bus.sfa_status = 3;
    AirModel model;
    SensorSchedule schedule(bus, model);
    for (bus.now = 0; bus.now <= 59000; bus.now += 10)
        schedule.Tick(bus.now);
    auto snapshot = model.Snapshot(59000);
    CHECK(snapshot.hcho.connected && snapshot.hcho.has_frame);
    CHECK(!snapshot.hcho.ready && !snapshot.hcho.has_value && snapshot.hcho.errors == 0);
    bus.sfa_status = 2;
    for (; bus.now <= 62000; bus.now += 10)
        schedule.Tick(bus.now);
    snapshot = model.Snapshot(62000);
    CHECK(snapshot.hcho.ready && snapshot.hcho.has_value && !snapshot.hcho.within_spec);
    CHECK(!snapshot.hcho.stale && snapshot.hcho.last_value_ms > 60000);
    NEAR(snapshot.sfa.ppb, 10.f, .001f);
    // Valid warm-up frames must not trigger any restart after the initial stop/start.
    unsigned stops = 0, starts = 0;
    for (const auto& tx : bus.writes) {
        if (tx.sensor != SensorId::Sfa40)
            continue;
        if (tx.command == 0x00AC)
            ++starts;
        if (tx.command == 0x50D2)
            ++stops;
    }
    CHECK(stops == 1 && starts == 1);
}

void CheckSfaStopExecutionDelay() {
    FakeBus bus;
    bus.command_duration_ms = 25;
    AirModel model;
    SensorSchedule schedule(bus, model);
    for (bus.now = 0; bus.now <= 2000; bus.now += 10)
        schedule.Tick(bus.now);
    bus.failed_reads = 3;
    for (; bus.now <= 20000; bus.now += 10)
        schedule.Tick(bus.now);
    uint64_t stop_completed = 0;
    bool saw_restart = false;
    for (const auto& tx : bus.writes) {
        if (tx.sensor != SensorId::Sfa40)
            continue;
        if (tx.command == 0x50D2)
            stop_completed = tx.time + 25;  // Simulated command transmission duration.
        if (tx.command == 0x00AC && stop_completed != 0) {
            CHECK(tx.time >= stop_completed + 25);  // Datasheet execution time after STOP.
            saw_restart = true;
        }
    }
    CHECK(saw_restart);
    CHECK(model.Snapshot(20000).hcho.last_value_ms > 15000);
}

void CheckSfaIdleReadDoesNotSkipStart() {
    FakeBus bus;
    bus.sfa_running = false;
    bus.idle_readable = true;
    AirModel model;
    SensorSchedule schedule(bus, model);
    for (bus.now = 0; bus.now <= 2000; bus.now += 10)
        schedule.Tick(bus.now);
    // An idle device can ACK and return CRC-valid bytes; only start initiates measurement.
    const auto snapshot = model.Snapshot(2000);
    CHECK(snapshot.hcho.ready && snapshot.hcho.has_value && !snapshot.hcho.stale);
    NEAR(snapshot.sfa.ppb, 10.f, .001f);
}

int main() {
    CheckSfaIdleReadDoesNotSkipStart();
    FakeBus bus;
    AirModel model;
    SensorSchedule schedule(bus, model);
    for (bus.now = 0; bus.now <= 2000; bus.now += 10)
        schedule.Tick(bus.now);
    CHECK(model.Snapshot(2000).hcho.has_value);
    CHECK(model.Snapshot(2000).co2.has_value);
    CHECK(model.Snapshot(2000).asc_enabled == 1);
    bool saw_stop = false, saw_asc = false, sfa_during_wait = false, sfa_started = false;
    for (const auto& tx : bus.writes) {
        if (tx.sensor == SensorId::Scd41 && tx.command == 0x3F86) {
            CHECK(tx.time == 0);
            saw_stop = true;
        }
        if (tx.sensor == SensorId::Scd41 && tx.command == 0x2313) {
            CHECK(tx.time >= 500);
            saw_asc = true;
        }
        if (tx.sensor == SensorId::Sfa40 && tx.time < 500)
            sfa_during_wait = true;
        CHECK(tx.command != 0x3615 && tx.command != 0x3632 && tx.command != 0x362F);
        if (tx.sensor == SensorId::Sfa40 && tx.command == 0x00AC)
            sfa_started = true;
    }
    CHECK(saw_stop && saw_asc && sfa_during_wait && sfa_started);
    FakeBus cold;
    cold.sfa_running = false;
    AirModel cold_model;
    SensorSchedule cold_schedule(cold, cold_model);
    uint64_t started = 0;
    bool has_started = false;
    for (cold.now = 0; cold.now <= 1500; cold.now += 10) {
        cold_schedule.Tick(cold.now);
        if (cold.last[1] == 0x00AC && !has_started) {
            started = cold.now;
            has_started = true;
        }
    }
    CHECK(has_started && cold_model.Snapshot(1500).hcho.has_value);
    for (const auto& tx : cold.writes) {
        if (tx.sensor == SensorId::Sfa40 && tx.command == 0xC0EB && tx.time > started)
            CHECK(tx.time - started >= 700);
    }
    CheckSfaReadRecovery(false);
    CheckSfaReadRecovery(true);
    CheckSfaReadRecovery(false, true);
    CheckSfaWarmup();
    CheckSfaStopExecutionDelay();
    std::puts(
        "schedule: warmup, read/CRC recovery, lost stop, cold start and shared-bus progress "
        "passed");
}
