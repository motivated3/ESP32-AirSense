#include "sensor_schedule.h"
#include "sensirion_protocol.h"
namespace air {
void SensorSchedule::Tick(uint64_t now_ms) {
    if (now_ms >= scd_due_)
        TickScd(now_ms);
    if (now_ms >= sfa_due_)
        TickSfa(now_ms);
}
void SensorSchedule::Fail(SensorId sensor, SensorError error) {
    model_.Failure(sensor, error);
    auto& count = failures_[static_cast<size_t>(sensor)];
    if (count < 3)
        ++count;
}
void SensorSchedule::TickScd(uint64_t now) {
    constexpr auto id = SensorId::Scd41;
    uint8_t bytes[9];
    switch (scd_) {
        case Scd::Stop:
            // Stop can NACK if already idle. The following idle commands establish recovery.
            bus_.Command(id, 0x3F86);
            scd_ = Scd::AscCommand;
            scd_due_ = now + 500;
            return;
        case Scd::AscCommand:
            if (bus_.Command(id, 0x2313)) {
                scd_ = Scd::AscRead;
                scd_due_ = now + 1;
            } else {
                Fail(id, SensorError::Transport);
                scd_ = Scd::Start;
                scd_due_ = now + 1;
            }
            return;
        case Scd::AscRead: {
            uint16_t asc;
            if (!bus_.Receive(id, bytes, 3))
                Fail(id, SensorError::Transport);
            else if (!DecodeWord(bytes, 3, asc))
                Fail(id, SensorError::Crc);
            else if (asc <= 1)
                model_.SetAscEnabled(asc != 0);
            scd_ = Scd::Start;
            scd_due_ = now;
            return;
        }
        case Scd::Start:
            if (!bus_.Command(id, 0x21B1)) {
                Fail(id, SensorError::Transport);
                scd_ = Scd::Stop;
                scd_due_ = now + 5000;
            } else {
                model_.Acknowledge(id);
                failures_[0] = 0;
                scd_ = Scd::ReadyCommand;
                scd_due_ = now + 1000;
            }
            return;
        case Scd::ReadyCommand:
            if (bus_.Command(id, 0xE4B8)) {
                scd_ = Scd::ReadyRead;
                scd_due_ = now + 1;
                return;
            }
            Fail(id, SensorError::Transport);
            break;
        case Scd::ReadyRead: {
            bool ready = false;
            if (!bus_.Receive(id, bytes, 3))
                Fail(id, SensorError::Transport);
            else if (!DecodeScd41Ready(bytes, 3, ready))
                Fail(id, SensorError::Crc);
            else {
                model_.Acknowledge(id);
                failures_[0] = 0;
                if (ready) {
                    scd_ = Scd::MeasureCommand;
                    scd_due_ = now;
                    return;
                }
            }
            break;
        }
        case Scd::MeasureCommand:
            if (bus_.Command(id, 0xEC05)) {
                scd_ = Scd::MeasureRead;
                scd_due_ = now + 1;
                return;
            }
            Fail(id, SensorError::Transport);
            break;
        case Scd::MeasureRead: {
            Scd41Reading value;
            if (!bus_.Receive(id, bytes, 9))
                Fail(id, SensorError::Transport);
            else if (!DecodeScd41(bytes, 9, value))
                Fail(id, SensorError::Crc);
            else {
                model_.ApplyScd41(value, now);
                failures_[0] = 0;
            }
            break;
        }
    }
    scd_ = failures_[0] >= 3 ? Scd::Stop : Scd::ReadyCommand;
    scd_due_ = now + (failures_[0] >= 3 ? 5000 : 1000);
}
void SensorSchedule::TickSfa(uint64_t now) {
    constexpr auto id = SensorId::Sfa40;
    uint8_t bytes[12];
    switch (sfa_) {
        case Sfa::Stop:
            // Establish idle explicitly at startup and after read/CRC failures.
            // A CRC-valid read alone does not prove measurement has been started.
            bus_.Command(id, 0x50D2);
            sfa_ = Sfa::StopWait;
            sfa_due_ = now;
            return;
        case Sfa::StopWait:
            // This tick began after stop completed. Its timestamp cannot predate the
            // transaction, even when shared-bus work delayed the previous tick.
            // Stop may NACK if already idle; allow its 25 ms execution time either way.
            sfa_ = Sfa::Start;
            sfa_due_ = now + 25;
            return;
        case Sfa::Start:
            if (!bus_.Command(id, 0x00AC)) {
                Fail(id, SensorError::Transport);
                // Retry stop too: if it was lost, start is illegal during measurement.
                sfa_ = Sfa::Stop;
                sfa_due_ = now + 5000;
            } else {
                model_.Acknowledge(id);
                failures_[1] = 0;
                sfa_ = Sfa::MeasureCommand;
                sfa_due_ = now + 700;
            }
            return;
        case Sfa::MeasureCommand:
            if (bus_.Command(id, 0xC0EB)) {
                sfa_ = Sfa::MeasureRead;
                sfa_due_ = now + 1;
                return;
            }
            Fail(id, SensorError::Transport);
            break;
        case Sfa::MeasureRead: {
            Sfa40Reading value;
            if (!bus_.Receive(id, bytes, 12))
                Fail(id, SensorError::Transport);
            else if (!DecodeSfa40(bytes, 12, value))
                Fail(id, SensorError::Crc);
            else {
                model_.ApplySfa40(value, now);
                failures_[1] = 0;
            }
            break;
        }
    }
    sfa_ = failures_[1] >= 3 ? Sfa::Stop : Sfa::MeasureCommand;
    sfa_due_ = now + (failures_[1] >= 3 ? 5000 : 1000);
}
}  // namespace air
