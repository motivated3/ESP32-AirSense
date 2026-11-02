#include "air_model.h"
namespace air {
void AirModel::Acknowledge(SensorId sensor) {
    auto& channel = sensor == SensorId::Scd41 ? state_.co2 : state_.hcho;
    channel.connected = true;
    transport_failures_[static_cast<size_t>(sensor)] = 0;
}
void AirModel::ApplyScd41(const Scd41Reading& value, uint64_t now_ms) {
    Acknowledge(SensorId::Scd41);
    auto& c = state_.co2;
    c.has_frame = true;
    c.last_frame_ms = now_ms;
    c.errors = 0;
    c.ready = value.ppm != 0;
    c.environment_ok = value.temperature >= -10 && value.temperature <= 60 && value.humidity <= 95;
    c.within_spec = c.ready && value.ppm >= 400 && value.ppm <= 5000 && c.environment_ok;
    if (!c.ready) {
        c.has_value = false;
        return;
    }
    state_.scd = value;
    c.has_value = true;
    c.last_value_ms = now_ms;
    if (c.within_spec)
        Record(Metric::Co2, value.ppm, now_ms);
}
void AirModel::ApplySfa40(const Sfa40Reading& value, uint64_t now_ms) {
    Acknowledge(SensorId::Sfa40);
    auto& c = state_.hcho;
    c.has_frame = true;
    c.last_frame_ms = now_ms;
    c.errors = 0;
    c.ready = value.ready;
    c.environment_ok = value.temperature >= 0 && value.temperature <= 50 && value.humidity >= 10 &&
                       value.humidity <= 90;
    c.within_spec = value.ready && value.within_spec && c.environment_ok;
    state_.sfa = value;
    if (!c.ready) {
        c.has_value = false;
        return;
    }
    c.has_value = true;
    c.last_value_ms = now_ms;
    if (c.within_spec)
        Record(Metric::Hcho, value.ppb, now_ms);
}
void AirModel::Failure(SensorId sensor, SensorError error) {
    auto& c = sensor == SensorId::Scd41 ? state_.co2 : state_.hcho;
    if (c.errors < UINT32_MAX)
        ++c.errors;
    if (error == SensorError::Transport) {
        auto& failures = transport_failures_[static_cast<size_t>(sensor)];
        if (failures < 3)
            ++failures;
        if (failures >= 3)
            c.connected = false;
    }
}
AirSnapshot AirModel::Snapshot(uint64_t now_ms) const {
    auto result = state_;
    result.now_ms = now_ms;
    result.co2.stale = result.co2.has_value && now_ms >= result.co2.last_value_ms &&
                       now_ms - result.co2.last_value_ms > 15000;
    result.hcho.stale = result.hcho.has_value && now_ms >= result.hcho.last_value_ms &&
                        now_ms - result.hcho.last_value_ms > 5000;
    return result;
}
const std::array<HistoryPoint, kHistorySize>& AirModel::History(Metric metric) const {
    return metric == Metric::Co2 ? co2_history_ : hcho_history_;
}
void AirModel::Record(Metric metric, float value, uint64_t now_ms) {
    const uint64_t bucket = now_ms / 5000;
    auto& history = metric == Metric::Co2 ? co2_history_ : hcho_history_;
    history[bucket % kHistorySize] = {true, value, bucket};
}
}  // namespace air
