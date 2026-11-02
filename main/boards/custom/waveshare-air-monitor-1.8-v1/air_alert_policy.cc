#include "air_alert_policy.h"
#include <algorithm>
#include <cmath>

namespace air {
namespace {
constexpr uint64_t kConfirmMs = 30000;
constexpr uint64_t kCo2MaxGapMs = 7500;
constexpr uint64_t kHchoMaxGapMs = 2000;

bool ValidFrame(const ChannelState& state, uint64_t now_ms, uint64_t freshness_ms) {
    return state.has_frame && state.has_value && state.connected && state.ready &&
           state.environment_ok && !state.stale && state.errors == 0 &&
           state.last_frame_ms == state.last_value_ms && state.last_value_ms <= now_ms &&
           now_ms - state.last_value_ms <= freshness_ms;
}

bool ValidCo2(const AirSnapshot& readings) {
    const auto& value = readings.scd;
    // The rated accuracy ends at 5000 ppm. A valid higher reading must still alert.
    return ValidFrame(readings.co2, readings.now_ms, 15000) && value.ppm != 0 &&
           std::isfinite(value.temperature) && value.temperature >= -10 &&
           value.temperature <= 60 && std::isfinite(value.humidity) && value.humidity >= 0 &&
           value.humidity <= 95;
}

bool ValidHcho(const AirSnapshot& readings) {
    const auto& value = readings.sfa;
    return ValidFrame(readings.hcho, readings.now_ms, 5000) && readings.hcho.within_spec &&
           value.ready && value.within_spec && (value.status & 3) == 0 &&
           std::isfinite(value.ppb) && value.ppb >= 0 && value.ppb <= 2000 &&
           std::isfinite(value.temperature) && value.temperature >= 0 && value.temperature <= 50 &&
           std::isfinite(value.humidity) && value.humidity >= 10 && value.humidity <= 90;
}
}  // namespace

AlertSettings AirAlertPolicy::NormalizeSettings(AlertSettings settings) {
    settings.co2_ppm = std::clamp(settings.co2_ppm, 600, 5000);
    settings.hcho_ppb = std::clamp(settings.hcho_ppb, 20, 500);
    return settings;
}

AlertSnapshot AirAlertPolicy::Update(const AirSnapshot& readings, const AlertSettings& settings) {
    const auto normalized = NormalizeSettings(settings);
    if (configured_) {
        if (normalized.co2_enabled != settings_.co2_enabled ||
            normalized.co2_ppm != settings_.co2_ppm)
            ResetChannel(0, readings.co2, readings.now_ms);
        if (normalized.hcho_enabled != settings_.hcho_enabled ||
            normalized.hcho_ppb != settings_.hcho_ppb)
            ResetChannel(1, readings.hcho, readings.now_ms);
    }
    configured_ = true;
    settings_ = normalized;

    const bool co2_valid = ValidCo2(readings);
    const bool hcho_valid = ValidHcho(readings);
    bool new_event = false;
    if (settings_.co2_enabled)
        new_event |=
            Advance(0, co2_valid, readings.co2, readings.now_ms, readings.scd.ppm,
                    settings_.co2_ppm, std::max(400, settings_.co2_ppm - 200), kCo2MaxGapMs);
    if (settings_.hcho_enabled)
        new_event |=
            Advance(1, hcho_valid, readings.hcho, readings.now_ms, readings.sfa.ppb,
                    settings_.hcho_ppb, std::max(0, settings_.hcho_ppb - 10), kHchoMaxGapMs);
    if (new_event && ++snapshot_.generation == 0)
        ++snapshot_.generation;
    snapshot_.unavailable =
        snapshot_.active & ((co2_valid ? 0 : kAlertCo2) | (hcho_valid ? 0 : kAlertHcho));
    acknowledged_ &= snapshot_.active;
    snapshot_.pending = snapshot_.active & ~acknowledged_;
    return snapshot_;
}

AlertSnapshot AirAlertPolicy::Snapshot() const { return snapshot_; }

void AirAlertPolicy::Acknowledge(uint32_t generation) {
    if (generation != snapshot_.generation)
        return;
    acknowledged_ |= snapshot_.active;
    snapshot_.pending = snapshot_.active & ~acknowledged_;
}

void AirAlertPolicy::ResetChannel(size_t index, const ChannelState& reading, uint64_t now_ms) {
    channels_[index] = {};
    auto& channel = channels_[index];
    // Reconfiguration cannot use the value already on screen as its first new sample.
    if (reading.has_value && reading.last_value_ms <= now_ms) {
        channel.has_sample = true;
        channel.last_sample_ms = reading.last_value_ms;
    }
    const uint8_t bit = uint8_t{1} << index;
    snapshot_.active &= ~bit;
    acknowledged_ &= ~bit;
}

bool AirAlertPolicy::Advance(size_t index, bool valid, const ChannelState& reading, uint64_t now_ms,
                             float value, int threshold, int clear_threshold, uint64_t max_gap_ms) {
    auto& channel = channels_[index];
    const auto sample_ms = reading.last_value_ms;
    if (!valid) {
        channel.timing = false;
        if (reading.has_value && sample_ms <= now_ms &&
            (!channel.has_sample || sample_ms > channel.last_sample_ms)) {
            channel.has_sample = true;
            channel.last_sample_ms = sample_ms;
        }
        return false;
    }
    if (channel.has_sample && sample_ms <= channel.last_sample_ms) {
        if (sample_ms < channel.last_sample_ms || now_ms - sample_ms > max_gap_ms)
            channel.timing = false;
        return false;
    }
    if (!channel.has_sample || sample_ms - channel.last_sample_ms > max_gap_ms)
        channel.timing = false;
    channel.has_sample = true;
    channel.last_sample_ms = sample_ms;

    const uint8_t bit = uint8_t{1} << index;
    const bool active = (snapshot_.active & bit) != 0;
    const bool confirming = active ? value <= clear_threshold : value > threshold;
    if (!confirming) {
        channel.timing = false;
        return false;
    }
    if (!channel.timing) {
        channel.timing = true;
        channel.since_ms = sample_ms;
        return false;
    }
    if (sample_ms - channel.since_ms < kConfirmMs)
        return false;

    channel.timing = false;
    if (active)
        snapshot_.active &= ~bit;
    else
        snapshot_.active |= bit;
    return !active;
}
}  // namespace air
