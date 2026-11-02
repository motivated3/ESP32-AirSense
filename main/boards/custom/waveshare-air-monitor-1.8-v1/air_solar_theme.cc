#include "air_solar_theme.h"
#include <chrono>
#include <cmath>
#include <numbers>

namespace air {
namespace {
constexpr int64_t kFirstUtcMs = 1704067200000LL;  // 2024-01-01
constexpr int64_t kEndUtcMs = 4102444800000LL;    // 2100-01-01 (exclusive)
bool ValidTime(int64_t utc_ms) { return utc_ms >= kFirstUtcMs && utc_ms < kEndUtcMs; }
}  // namespace
std::optional<bool> IsSolarNight(SolarLocation location, int64_t utc_ms) {
    if (!location.valid() || !ValidTime(utc_ms))
        return std::nullopt;
    using namespace std::chrono;
    constexpr double radians = std::numbers::pi / 180.;
    const sys_time<milliseconds> now{milliseconds{utc_ms}};
    const auto day = floor<days>(now);
    const year_month_day date{day};
    const auto year_start = sys_days{date.year() / January / 1};
    const double utc_minutes = duration<double, std::ratio<60>>(now - day).count();
    // NOAA general solar-position approximation, UTC (timezone = 0).
    // https://gml.noaa.gov/grad/solcalc/solareqns.PDF
    const double gamma = 2 * std::numbers::pi / (date.year().is_leap() ? 366 : 365) *
                         ((day - year_start).count() + (utc_minutes / 60 - 12) / 24);
    const double equation =
        229.18 * (0.000075 + 0.001868 * std::cos(gamma) - 0.032077 * std::sin(gamma) -
                  0.014615 * std::cos(2 * gamma) - 0.040849 * std::sin(2 * gamma));
    const double declination = 0.006918 - 0.399912 * std::cos(gamma) + 0.070257 * std::sin(gamma) -
                               0.006758 * std::cos(2 * gamma) + 0.000907 * std::sin(2 * gamma) -
                               0.002697 * std::cos(3 * gamma) + 0.00148 * std::sin(3 * gamma);
    const double latitude = location.latitude_e6 / 1e6 * radians;
    const double angle =
        (std::fmod(utc_minutes + equation + 4 * location.longitude_e6 / 1e6, 1440.) / 4 - 180) *
        radians;
    const double zenith_cosine = std::sin(latitude) * std::sin(declination) +
                                 std::cos(latitude) * std::cos(declination) * std::cos(angle);
    return zenith_cosine < std::cos(90.833 * radians);
}
bool SolarThemeClock::Synchronize(int64_t utc_ms, uint64_t uptime_ms) {
    if (!ValidTime(utc_ms))
        return false;
    utc_ms_ = utc_ms;
    uptime_ms_ = uptime_ms;
    return true;
}
std::optional<bool> SolarThemeClock::Night(uint64_t uptime_ms) const {
    if (!utc_ms_ || uptime_ms < uptime_ms_ ||
        uptime_ms - uptime_ms_ >= uint64_t(kEndUtcMs - utc_ms_))
        return std::nullopt;
    return IsSolarNight(location_, utc_ms_ + static_cast<int64_t>(uptime_ms - uptime_ms_));
}
}  // namespace air
