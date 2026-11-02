#pragma once
#include <array>
#include <cstdint>
#include "air_alert_policy.h"

namespace air {
enum class Page { Home, Trend, Settings };
enum class ThemeMode { Day, Night, Auto };
class AirUiState {
public:
    uint64_t Notify(const char* text, uint64_t now_ms, int duration_ms);
    void Expire(uint64_t id, uint64_t now_ms);
    void Tick(uint64_t now_ms) { Expire(notice_id_, now_ms); }
    const char* notice() const { return notice_.data(); }
    void SetPage(Page page) {
        page_ = page;
        drawer_ = false;
    }
    Page page() const { return page_; }
    void SetDrawer(bool open) { drawer_ = open; }
    bool drawer() const { return drawer_; }
    void Back();
    void SetTheme(bool night) { night_ = night; }
    void SetThemeMode(ThemeMode mode) {
        theme_mode_ = mode;
        if (mode != ThemeMode::Auto)
            night_ = mode == ThemeMode::Night;
    }
    ThemeMode theme_mode() const { return theme_mode_; }
    bool night() const { return night_; }
    void SetDisplayOn(bool on) { display_on_ = on; }
    bool display_on() const { return display_on_; }
    void SetBrightness(int value);
    int brightness() const { return night_ ? night_brightness_ : day_brightness_; }
    bool reduce_motion = false;
    bool voice_enabled = true;
    AlertSettings alerts;
    int day_brightness() const { return day_brightness_; }
    int night_brightness() const { return night_brightness_; }

private:
    Page page_ = Page::Home;
    bool drawer_ = false;
    bool night_ = false;
    ThemeMode theme_mode_ = ThemeMode::Day;
    bool display_on_ = true;
    int day_brightness_ = 70;
    int night_brightness_ = 15;
    uint64_t notice_id_ = 0;
    uint64_t notice_until_ = 0;
    std::array<char, 96> notice_{};
};
}  // namespace air
