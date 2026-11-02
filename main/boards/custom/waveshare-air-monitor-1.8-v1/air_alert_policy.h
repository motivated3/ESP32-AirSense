#pragma once
#include "air_types.h"

namespace air {
constexpr uint8_t kAlertCo2 = 1;
constexpr uint8_t kAlertHcho = 2;

struct AlertSettings {
    bool co2_enabled = true;
    bool hcho_enabled = true;
    bool sound = true;
    int co2_ppm = 1500;
    int hcho_ppb = 80;
};

struct AlertSnapshot {
    uint32_t generation = 0;
    uint8_t active = 0;
    uint8_t unavailable = 0;
    uint8_t pending = 0;
};

class AirAlertPolicy {
public:
    static AlertSettings NormalizeSettings(AlertSettings settings);
    AlertSnapshot Update(const AirSnapshot& readings, const AlertSettings& settings);
    AlertSnapshot Snapshot() const;
    void Acknowledge(uint32_t generation);

private:
    struct Channel {
        bool has_sample = false;
        bool timing = false;
        uint64_t last_sample_ms = 0;
        uint64_t since_ms = 0;
    };

    void ResetChannel(size_t index, const ChannelState& reading, uint64_t now_ms);
    bool Advance(size_t index, bool valid, const ChannelState& reading, uint64_t now_ms,
                 float value, int threshold, int clear_threshold, uint64_t max_gap_ms);

    Channel channels_[2]{};
    AlertSettings settings_;
    AlertSnapshot snapshot_;
    uint8_t acknowledged_ = 0;
    bool configured_ = false;
};
}  // namespace air
