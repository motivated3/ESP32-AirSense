#pragma once
#include <cstdint>
#include <limits>
#include <optional>

namespace air {
struct SolarLocation {
    int32_t latitude_e6 = std::numeric_limits<int32_t>::min();
    int32_t longitude_e6 = std::numeric_limits<int32_t>::min();
    bool valid() const {
        return latitude_e6 >= -90000000 && latitude_e6 <= 90000000 && longitude_e6 >= -180000000 &&
               longitude_e6 <= 180000000;
    }
    bool operator==(const SolarLocation&) const = default;
};
std::optional<bool> IsSolarNight(SolarLocation location, int64_t utc_ms);

// UTC is established afresh each boot; cached coordinates alone cannot validate time.
class SolarThemeClock {
public:
    void SetLocation(SolarLocation location) { location_ = location; }
    SolarLocation location() const { return location_; }
    bool Synchronize(int64_t utc_ms, uint64_t uptime_ms);
    std::optional<bool> Night(uint64_t uptime_ms) const;

private:
    SolarLocation location_;
    int64_t utc_ms_ = 0;
    uint64_t uptime_ms_ = 0;
};
}  // namespace air
