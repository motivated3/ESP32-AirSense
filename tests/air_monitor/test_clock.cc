#include <cstdlib>
#include <cstring>
#include <limits>
#include <string>

#include "air_clock.h"
#include "test_support.h"

int main() {
    // Literal epochs represent the local fields already stored by OTA time sync.
    // These cases catch extra timezone offsets, rounding and calendar rollover bugs.
    const struct {
        std::time_t epoch;
        const char* expected;
    } cases[] = {
        {1792766160, "10-23 14:36"},
        {1792766219, "10-23 14:36"},
        {1792766220, "10-23 14:37"},
        {1792799999, "10-23 23:59"},
        {1792800000, "10-24 00:00"},
        {1793491199, "10-31 23:59"},
        {1793491200, "11-01 00:00"},
        {1798761599, "12-31 23:59"},
        {1798761600, "01-01 00:00"},
        {1709251199, "02-29 23:59"},
        {1709251200, "03-01 00:00"},
        {1704067199, "--:--"},
        {1704067200, "01-01 00:00"},
        {4102444799, "12-31 23:59"},
        {4102444800, "--:--"},
        {0, "--:--"},
        {1, "--:--"},
        {-1, "--:--"},
        {std::numeric_limits<std::time_t>::max(), "--:--"},
    };

    const char* original_tz = std::getenv("TZ");
    const bool had_tz = original_tz != nullptr;
    const std::string saved_tz = had_tz ? original_tz : "";
    for (const char* timezone : {"UTC0", "CST-8", "EST5EDT"}) {
        CHECK(setenv("TZ", timezone, 1) == 0);
        tzset();
        for (const auto& item : cases) {
            const auto result = air::FormatLocalClock(item.epoch);
            CHECK(result.back() == '\0');
            if (std::strcmp(result.data(), item.expected) != 0) {
                std::fprintf(stderr, "clock: epoch=%lld TZ=%s expected='%s' actual='%s'\n",
                             static_cast<long long>(item.epoch), timezone, item.expected,
                             result.data());
                return 1;
            }
        }
        CHECK(std::strcmp(std::getenv("TZ"), timezone) == 0);
    }
    if (had_tz) {
        CHECK(setenv("TZ", saved_tz.c_str(), 1) == 0);
    } else {
        CHECK(unsetenv("TZ") == 0);
    }
    tzset();
    std::puts("clock: local fields, calendar boundaries, invalid time and TZ independence passed");
}
