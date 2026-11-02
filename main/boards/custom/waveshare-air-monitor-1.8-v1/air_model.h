#pragma once
#include <array>
#include "air_types.h"

namespace air {
class AirModel {
public:
    void ApplyScd41(const Scd41Reading& value, uint64_t now_ms);
    void ApplySfa40(const Sfa40Reading& value, uint64_t now_ms);
    void Failure(SensorId sensor, SensorError error);
    void Acknowledge(SensorId sensor);
    void SetAscEnabled(bool enabled) { state_.asc_enabled = enabled ? 1 : 0; }
    AirSnapshot Snapshot(uint64_t now_ms) const;
    const std::array<HistoryPoint, kHistorySize>& History(Metric metric) const;

private:
    void Record(Metric metric, float value, uint64_t now_ms);
    AirSnapshot state_;
    std::array<HistoryPoint, kHistorySize> co2_history_{};
    std::array<HistoryPoint, kHistorySize> hcho_history_{};
    uint32_t transport_failures_[2]{};
};
}  // namespace air
