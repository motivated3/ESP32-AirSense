#include <chrono>
#include <limits>
#include "air_solar_theme.h"
#include "air_ui_state.h"
#include "test_support.h"

using namespace std::chrono;
using namespace air;
int64_t Utc(int year, unsigned month, unsigned day, int hour, int minute = 0) {
    return duration_cast<milliseconds>(
               (sys_days{std::chrono::year{year} / month / day} + hours{hour} + minutes{minute})
                   .time_since_epoch())
        .count();
}
int main() {
    SolarLocation beijing{39904000, 116407000};
    CHECK(beijing.valid());
    CHECK((SolarLocation{0, 0}.valid()));
    CHECK((SolarLocation{90000000, -180000000}.valid()));
    CHECK(!(SolarLocation{}.valid()));
    CHECK(!(SolarLocation{90000001, 0}.valid()));
    CHECK(!(SolarLocation{0, 180000001}.valid()));
    // Wide margins around known winter/summer rise/set catch longitude and UTC sign errors.
    CHECK(IsSolarNight(beijing, Utc(2026, 6, 21, 20, 30)).value());   // 04:30 next day CST
    CHECK(!IsSolarNight(beijing, Utc(2026, 6, 21, 21, 0)).value());   // 05:00
    CHECK(!IsSolarNight(beijing, Utc(2026, 6, 21, 11, 30)).value());  // 19:30
    CHECK(IsSolarNight(beijing, Utc(2026, 6, 21, 12, 0)).value());    // 20:00
    CHECK(IsSolarNight(beijing, Utc(2026, 12, 21, 23, 0)).value());   // 07:00
    CHECK(!IsSolarNight(beijing, Utc(2026, 12, 21, 0, 0)).value());   // 08:00
    CHECK(!IsSolarNight({-33869000, 151209000}, Utc(2024, 2, 29, 1)).value());
    CHECK(!IsSolarNight({40713000, -74006000}, Utc(2026, 6, 21, 16)).value());
    CHECK(IsSolarNight({40713000, -74006000}, Utc(2026, 6, 21, 4)).value());
    for (int hour : {0, 6, 12, 18}) {
        CHECK(!IsSolarNight({90000000, 0}, Utc(2026, 6, 21, hour)).value());
        CHECK(IsSolarNight({90000000, 0}, Utc(2026, 12, 21, hour)).value());
        CHECK(IsSolarNight({-90000000, 0}, Utc(2026, 6, 21, hour)).value());
        CHECK(!IsSolarNight({-90000000, 0}, Utc(2026, 12, 21, hour)).value());
    }
    CHECK(!IsSolarNight({}, Utc(2026, 1, 1, 12)));
    CHECK(!IsSolarNight(beijing, 0));
    CHECK(!IsSolarNight(beijing, -1));
    CHECK(!IsSolarNight(beijing, std::numeric_limits<int64_t>::max()));
    CHECK(!IsSolarNight(beijing, Utc(2100, 1, 1, 0)));
    SolarThemeClock clock;
    clock.SetLocation(beijing);
    CHECK(!clock.Night(0));  // Cached location never resurrects a pre-reboot clock.
    CHECK(!clock.Synchronize(0, 1000));
    CHECK(clock.Synchronize(Utc(2026, 6, 21, 20, 30), 1000));
    CHECK(clock.Night(1000).value());
    CHECK(!clock.Night(1000 + 30 * 60000).value());   // Offline advance across sunrise.
    CHECK(clock.Night(1000 + 24 * 3600000).value());  // Offline next day.
    CHECK(!clock.Night(999));  // Reject uptime regression / a different boot.
    CHECK(!clock.Synchronize(-1, 1000));
    CHECK(!clock.Night(std::numeric_limits<uint64_t>::max()));
    AirUiState state;
    state.SetThemeMode(ThemeMode::Night);
    CHECK(state.night());
    state.SetBrightness(12);
    state.SetThemeMode(ThemeMode::Auto);
    CHECK(state.night() && state.brightness() == 12);
    state.SetTheme(false);  // Automatic switch preserves selected mode and brightness pair.
    CHECK(state.theme_mode() == ThemeMode::Auto && state.brightness() == 70);
    state.SetThemeMode(ThemeMode::Day);
    CHECK(!state.night());
    state.SetThemeMode(ThemeMode::Night);
    CHECK(state.brightness() == 12);
    std::puts("solar theme: UTC, cached location, offline advance, polar and mode checks passed");
}
