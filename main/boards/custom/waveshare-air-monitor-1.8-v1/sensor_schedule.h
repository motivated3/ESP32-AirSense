#pragma once
#include "air_model.h"

namespace air {
class SensorBus {
public:
    virtual ~SensorBus() = default;
    virtual bool Command(SensorId sensor, uint16_t command) = 0;
    virtual bool Receive(SensorId sensor, uint8_t* data, size_t length) = 0;
};
class SensorSchedule {
public:
    SensorSchedule(SensorBus& bus, AirModel& model) : bus_(bus), model_(model) {}
    void Tick(uint64_t now_ms);

private:
    enum class Scd {
        Stop,
        AscCommand,
        AscRead,
        Start,
        ReadyCommand,
        ReadyRead,
        MeasureCommand,
        MeasureRead
    };
    enum class Sfa { Stop, StopWait, Start, MeasureCommand, MeasureRead };
    void TickScd(uint64_t now_ms);
    void TickSfa(uint64_t now_ms);
    void Fail(SensorId sensor, SensorError error);
    SensorBus& bus_;
    AirModel& model_;
    Scd scd_ = Scd::Stop;
    Sfa sfa_ = Sfa::Stop;
    uint64_t scd_due_ = 0;
    uint64_t sfa_due_ = 0;
    unsigned failures_[2]{};
};
}  // namespace air
