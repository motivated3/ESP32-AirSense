#pragma once
#include <array>
#include <ctime>

namespace air {
inline std::array<char, 12> FormatLocalClock(std::time_t local_epoch) {
    const std::array<char, 12> unavailable{"--:--"};
    std::tm fields{};
    // OTA already adds timezone_offset before setting the system clock.
    if (local_epoch < 0 || gmtime_r(&local_epoch, &fields) == nullptr || fields.tm_year < 124 ||
        fields.tm_year > 199) {
        return unavailable;
    }
    std::array<char, 12> result{};
    if (std::strftime(result.data(), result.size(), "%m-%d %H:%M", &fields) != 11) {
        return unavailable;
    }
    return result;
}
}  // namespace air
