#pragma once
#include <cstddef>
#include <cstdint>

namespace air {
struct Scd41Reading {
    uint16_t ppm = 0;
    float temperature = 0;
    float humidity = 0;
};
struct Sfa40Reading {
    float ppb = 0;
    float temperature = 0;
    float humidity = 0;
    bool ready = false;
    bool within_spec = false;
    uint8_t status = 3;
};
enum class Metric { Co2, Hcho };
enum class SensorId { Scd41, Sfa40 };
enum class SensorError { Transport, Crc };
struct ChannelState {
    bool has_value = false;
    bool has_frame = false;
    bool connected = false;
    bool ready = false;
    bool within_spec = false;
    bool stale = false;
    bool environment_ok = true;
    uint32_t errors = 0;
    uint64_t last_frame_ms = 0;
    uint64_t last_value_ms = 0;
};
struct AirSnapshot {
    Scd41Reading scd;
    Sfa40Reading sfa;
    ChannelState co2;
    ChannelState hcho;
    int8_t asc_enabled = -1;
    uint64_t now_ms = 0;
};
constexpr size_t kHistorySize = 360;
struct HistoryPoint {
    bool valid = false;
    float value = 0;
    uint64_t bucket = 0;
};
struct PowerSnapshot {
    bool valid = false;
    bool vbus = false;
    bool battery_present = false;
    bool charging = false;
    bool discharging = false;
    int battery_percent = -1;
    bool display_on = true;
    bool shutting_down = false;
};
}  // namespace air
