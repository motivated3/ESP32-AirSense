#include <limits>
#include "air_alert_policy.h"
#include "air_model.h"
#include "test_support.h"

using namespace air;

namespace {
struct Fixture {
    AirModel model;
    AirAlertPolicy policy;
    AlertSettings settings;

    AlertSnapshot Tick(uint64_t now) { return policy.Update(model.Snapshot(now), settings); }
    AlertSnapshot Co2(uint64_t now, uint16_t ppm = 1600) {
        model.ApplyScd41({ppm, 25, 50}, now);
        return Tick(now);
    }
    AlertSnapshot Hcho(uint64_t now, float ppb = 90) {
        model.ApplySfa40({ppb, 25, 50, true, true, 0}, now);
        return Tick(now);
    }
    void HighCo2(uint64_t start, uint64_t end) {
        for (uint64_t now = start; now <= end; now += 5000)
            Co2(now);
    }
    void HighHcho(uint64_t start, uint64_t end) {
        for (uint64_t now = start; now <= end; now += 1000)
            Hcho(now);
    }
};

void ConfirmationUsesNewSamplesAndStrictThreshold() {
    Fixture f;
    f.HighCo2(0, 25000);
    CHECK(f.Tick(29999).active == 0);
    CHECK(f.Tick(30000).active == 0);  // A UI tick cannot replace the next sample.
    auto alert = f.Co2(30000);
    CHECK(alert.active == kAlertCo2 && alert.pending == kAlertCo2);
    CHECK(alert.generation == 1 && alert.unavailable == 0);
    CHECK(f.Tick(31000).generation == 1);

    Fixture equal;
    for (uint64_t now = 0; now <= 40000; now += 5000)
        CHECK(equal.Co2(now, 1500).active == 0);
    Fixture repeated;
    repeated.Co2(0);
    for (uint64_t now = 100; now < 50000; now += 100)
        CHECK(repeated.Tick(now).active == 0);
    repeated.Co2(50000);
    CHECK(repeated.policy.Snapshot().active == 0);

    Fixture late;
    const uint64_t start = (uint64_t{1} << 32) + 100;
    late.HighCo2(start, start + 30000);
    CHECK(late.policy.Snapshot().active == kAlertCo2);
}

void MissingOrInvalidSamplesRestartConfirmation() {
    Fixture gap;
    gap.HighCo2(0, 20000);
    gap.HighCo2(30000, 55000);
    CHECK(gap.policy.Snapshot().active == 0);
    CHECK(gap.Co2(60000).active == kAlertCo2);

    Fixture crc;
    crc.HighCo2(0, 25000);
    crc.model.Failure(SensorId::Scd41, SensorError::Crc);
    CHECK(crc.Tick(26000).active == 0);
    crc.HighCo2(30000, 55000);
    CHECK(crc.policy.Snapshot().active == 0);
    CHECK(crc.Co2(60000).active == kAlertCo2);

    Fixture environment;
    environment.HighCo2(0, 25000);
    environment.model.ApplyScd41({1600, 61, 50}, 30000);
    CHECK(environment.Tick(30000).active == 0);
    environment.HighCo2(35000, 60000);
    CHECK(environment.policy.Snapshot().active == 0);
    CHECK(environment.Co2(65000).active == kAlertCo2);
}

void RecoveryRequiresNewLowSamplesAndHysteresis() {
    Fixture f;
    f.HighCo2(0, 30000);
    f.policy.Acknowledge(0);  // A stale UI callback cannot acknowledge a new event.
    CHECK(f.policy.Snapshot().pending == kAlertCo2);
    f.policy.Acknowledge(1);
    CHECK(f.policy.Snapshot().pending == 0);
    CHECK(f.Co2(35000, 1300).active == kAlertCo2);
    CHECK(f.Co2(40000, 1300).active == kAlertCo2);
    CHECK(f.Co2(45000, 1300).active == kAlertCo2);
    CHECK(f.Co2(50000, 1301).active == kAlertCo2);  // Hysteresis band breaks recovery.
    for (uint64_t now = 55000; now <= 80000; now += 5000)
        CHECK(f.Co2(now, 1300).active == kAlertCo2);
    CHECK(f.Tick(85000).active == kAlertCo2);
    CHECK(f.Co2(85000, 1300).active == 0);
    f.HighCo2(90000, 120000);
    CHECK(f.policy.Snapshot().generation == 2);
    CHECK(f.policy.Snapshot().pending == kAlertCo2);
}

void ActiveFaultsRetainEventUntilMeasuredRecovery() {
    Fixture f;
    f.HighCo2(0, 30000);
    f.policy.Acknowledge(1);
    for (int attempt = 0; attempt < 3; ++attempt)
        f.model.Failure(SensorId::Scd41, SensorError::Transport);
    auto fault = f.Tick(31000);
    CHECK(fault.active == kAlertCo2 && fault.unavailable == kAlertCo2 && fault.pending == 0);
    CHECK(f.Tick(90000).active == kAlertCo2);
    for (uint64_t now = 100000; now < 130000; now += 5000) {
        auto value = f.Co2(now, 1000);
        CHECK(value.active == kAlertCo2 && value.unavailable == 0);
    }
    CHECK(f.Co2(130000, 1000).active == 0);

    Fixture stale;
    stale.HighCo2(0, 30000);
    CHECK(stale.Tick(45001).unavailable == kAlertCo2);
    CHECK(stale.Tick(45001).active == kAlertCo2);
    stale.model.ApplyScd41({0, 25, 50}, 50000);
    CHECK(stale.Tick(50000).unavailable == kAlertCo2);
    stale.model.ApplyScd41({1000, 25, -1}, 55000);
    CHECK(stale.Tick(55000).unavailable == kAlertCo2);
}

void HchoRejectsUnstableAndMalformedReadings() {
    Fixture f;
    for (uint64_t now = 0; now <= 40000; now += 1000)
        CHECK(f.Hcho(now, 80).active == 0);
    f.HighHcho(41000, 71000);
    CHECK(f.policy.Snapshot().active == kAlertHcho);
    f.policy.Acknowledge(1);

    for (const auto reading : {
             Sfa40Reading{0, 25, 50, false, false, 3},
             Sfa40Reading{0, 25, 50, true, false, 2},
             Sfa40Reading{0, 25, 50, true, true, 1},
             Sfa40Reading{-1, 25, 50, true, true, 0},
             Sfa40Reading{2000.1f, 25, 50, true, true, 0},
             Sfa40Reading{std::numeric_limits<float>::quiet_NaN(), 25, 50, true, true, 0},
             Sfa40Reading{std::numeric_limits<float>::infinity(), 25, 50, true, true, 0},
             Sfa40Reading{0, 25, 91, true, true, 0},
             Sfa40Reading{0, std::numeric_limits<float>::quiet_NaN(), 50, true, true, 0},
         }) {
        f.model.ApplySfa40(reading, 72000);
        const auto alert = f.Tick(72000);
        CHECK(alert.active == kAlertHcho && alert.unavailable == kAlertHcho);
    }
    for (uint64_t now = 73000; now < 103000; now += 1000)
        CHECK(f.Hcho(now, 70).active == kAlertHcho);
    CHECK(f.Hcho(103000, 70).active == 0);

    Fixture provisional;
    for (uint64_t now = 0; now <= 50000; now += 1000) {
        provisional.model.ApplySfa40({100, 25, 50, true, false, 2}, now);
        CHECK(provisional.Tick(now).active == 0);
    }
    provisional.HighHcho(51000, 81000);
    CHECK(provisional.policy.Snapshot().active == kAlertHcho);

    Fixture high;
    for (uint64_t now = 0; now <= 30000; now += 1000)
        high.Hcho(now, 2000);
    CHECK(high.policy.Snapshot().active == kAlertHcho);
}

void Co2AboveRatedAccuracyStillAlerts() {
    Fixture f;
    for (uint64_t now = 0; now <= 30000; now += 5000)
        f.Co2(now, 6000);
    CHECK(!f.model.Snapshot(30000).co2.within_spec);
    CHECK(f.policy.Snapshot().active == kAlertCo2);

    Fixture forged;
    for (uint64_t now = 0; now <= 40000; now += 5000) {
        forged.model.ApplyScd41({1600, 25, 50}, now);
        auto raw = forged.model.Snapshot(now);
        raw.scd.humidity = std::numeric_limits<float>::infinity();
        CHECK(forged.policy.Update(raw, forged.settings).active == 0);
    }
}

void MergedAndLaterEventsHaveCorrectAcknowledgement() {
    Fixture together;
    for (uint64_t now = 0; now <= 30000; now += 1000) {
        together.model.ApplySfa40({90, 25, 50, true, true, 0}, now);
        if (now % 5000 == 0)
            together.model.ApplyScd41({1600, 25, 50}, now);
        together.Tick(now);
    }
    auto merged = together.policy.Snapshot();
    CHECK(merged.active == (kAlertCo2 | kAlertHcho));
    CHECK(merged.pending == (kAlertCo2 | kAlertHcho) && merged.generation == 1);
    together.policy.Acknowledge(1);
    CHECK(together.policy.Snapshot().pending == 0);

    Fixture later;
    later.HighCo2(0, 30000);
    later.policy.Acknowledge(1);
    for (uint64_t now = 31000; now <= 61000; now += 1000) {
        later.model.ApplySfa40({90, 25, 50, true, true, 0}, now);
        if (now % 5000 == 0)
            later.model.ApplyScd41({1600, 25, 50}, now);
        later.Tick(now);
    }
    CHECK(later.policy.Snapshot().generation == 2);
    CHECK(later.policy.Snapshot().active == (kAlertCo2 | kAlertHcho));
    CHECK(later.policy.Snapshot().pending == kAlertHcho);
    later.policy.Acknowledge(1);
    CHECK(later.policy.Snapshot().pending == kAlertHcho);
    later.policy.Acknowledge(2);
    CHECK(later.policy.Snapshot().pending == 0);
}

void ConfigurationChangesWaitForNewSamples() {
    Fixture f;
    f.HighCo2(0, 30000);
    f.settings.sound = false;
    CHECK(f.Tick(30100).active == kAlertCo2);
    f.settings.co2_ppm = 1400;
    CHECK(f.Tick(30200).active == 0);
    CHECK(f.Tick(34000).active == 0);
    f.HighCo2(35000, 60000);
    CHECK(f.policy.Snapshot().active == 0);
    CHECK(f.Co2(65000).generation == 2);
    f.settings.co2_enabled = false;
    CHECK(f.Tick(65100).active == 0);
    f.Co2(70000);
    f.settings.co2_enabled = true;
    CHECK(f.Tick(70100).active == 0);
    f.HighCo2(75000, 100000);
    CHECK(f.policy.Snapshot().active == 0);
    CHECK(f.Co2(105000).generation == 3);

    const auto bounded = AirAlertPolicy::NormalizeSettings({false, true, false, -1, 9000});
    CHECK(bounded.co2_ppm == 600 && bounded.hcho_ppb == 500);
    CHECK(!bounded.co2_enabled && bounded.hcho_enabled && !bounded.sound);
    const auto opposite = AirAlertPolicy::NormalizeSettings({true, true, true, 9000, -1});
    CHECK(opposite.co2_ppm == 5000 && opposite.hcho_ppb == 20);
}

void InvalidTimestampsAndFramesCannotAdvanceDwell() {
    Fixture f;
    f.HighCo2(0, 25000);
    auto stale_frame = f.model.Snapshot(30000);
    stale_frame.co2.last_frame_ms = 30000;
    CHECK(f.policy.Update(stale_frame, f.settings).active == 0);
    f.HighCo2(30000, 55000);
    CHECK(f.policy.Snapshot().active == 0);
    CHECK(f.Co2(60000).active == kAlertCo2);

    Fixture future;
    future.HighCo2(0, 25000);
    future.model.ApplyScd41({1600, 25, 50}, 30000);
    CHECK(future.Tick(29999).active == 0);
    future.HighCo2(30000, 55000);
    CHECK(future.policy.Snapshot().active == 0);
    CHECK(future.Co2(60000).active == kAlertCo2);

    Fixture backward;
    backward.HighCo2(0, 25000);
    CHECK(backward.Co2(20000).active == 0);
    backward.HighCo2(30000, 55000);
    CHECK(backward.policy.Snapshot().active == 0);
    CHECK(backward.Co2(60000).active == kAlertCo2);
}
}  // namespace

int main() {
    ConfirmationUsesNewSamplesAndStrictThreshold();
    MissingOrInvalidSamplesRestartConfirmation();
    RecoveryRequiresNewLowSamplesAndHysteresis();
    ActiveFaultsRetainEventUntilMeasuredRecovery();
    HchoRejectsUnstableAndMalformedReadings();
    Co2AboveRatedAccuracyStillAlerts();
    MergedAndLaterEventsHaveCorrectAcknowledgement();
    ConfigurationChangesWaitForNewSamples();
    InvalidTimestampsAndFramesCannotAdvanceDwell();
    std::puts("alert policy: confirmation, recovery, faults, generations and settings passed");
}
