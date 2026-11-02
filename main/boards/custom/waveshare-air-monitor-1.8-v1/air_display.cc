#include "air_display.h"
#include <esp_lvgl_port.h>
#include <esp_timer.h>
#include <wifi_manager.h>
#include <algorithm>
#include <cstdio>
#include <cstring>
#include <ctime>
#include "air_fonts.h"
#include "application.h"
#include "lvgl_theme.h"
#include "settings.h"
#include "storage_init.h"

namespace air {
AirDisplay::AirDisplay(esp_lcd_panel_io_handle_t io, esp_lcd_panel_handle_t panel,
                       AirSensors& sensors, AirHardware& hardware, AirViewCallbacks callbacks)
    : SpiLcdDisplay(io, panel, 368, 448, 0, 0, false, false, false, MemoryPolicy::Compact),
      sensors_(sensors),
      hardware_(hardware),
      callbacks_(std::move(callbacks)) {
    Settings prefs("air");
    state_.SetTheme(false);
    state_.SetBrightness(prefs.GetInt("day", 70));
    state_.SetTheme(true);
    state_.SetBrightness(prefs.GetInt("night_level", 15));
    state_.SetTheme(prefs.GetBool("night", false));
    const int theme_mode = prefs.GetInt("theme_mode", state_.night() ? 1 : 0);
    state_.SetThemeMode(theme_mode >= 0 && theme_mode <= 2
                            ? static_cast<ThemeMode>(theme_mode)
                            : (state_.night() ? ThemeMode::Night : ThemeMode::Day));
    solar_clock_.SetLocation(
        {prefs.GetInt("solar_lat", INT32_MIN), prefs.GetInt("solar_lon", INT32_MIN)});
    state_.reduce_motion = prefs.GetBool("reduce_motion", false);
    state_.voice_enabled = prefs.GetBool("voice", true);
    state_.alerts.co2_enabled = prefs.GetBool("alert_co2", true);
    state_.alerts.hcho_enabled = prefs.GetBool("alert_hcho", true);
    state_.alerts.sound = prefs.GetBool("alert_sound", true);
    state_.alerts.co2_ppm = prefs.GetInt("co2_limit", 1500);
    state_.alerts.hcho_ppb = prefs.GetInt("hcho_limit", 80);
    state_.alerts = AirAlertPolicy::NormalizeSettings(state_.alerts);
    voice_enabled_ = state_.voice_enabled;
    initial_brightness_ = state_.brightness();
    brightness_ = initial_brightness_;
    callbacks_.now_ms = []() { return static_cast<uint64_t>(esp_timer_get_time() / 1000); };
    // OTA already includes the server timezone offset in this system clock.
    callbacks_.wall_time = []() { return std::time(nullptr); };
    callbacks_.history = [this](Metric metric, std::array<HistoryPoint, kHistorySize>& history) {
        sensors_.CopyHistory(metric, history);
    };
    const auto voice_callback = callbacks_.voice_enabled;
    callbacks_.voice_enabled = [this, voice_callback](bool enabled) {
        voice_enabled_ = enabled;
        if (voice_callback)
            voice_callback(enabled);
    };
    callbacks_.preferences = [this]() { ++preferences_generation_; };
    const auto volume_callback = callbacks_.volume;
    callbacks_.volume = [this, volume_callback](int value) { QueueVolume(value, volume_callback); };
    callbacks_.acknowledge_alert = [this](uint32_t generation) {
        alert_policy_.Acknowledge(generation);
        const auto alerts = alert_policy_.Snapshot();
        alert_sound_token_ = alerts.pending && state_.alerts.sound ? alerts.generation : 0;
    };
    callbacks_.alerts_changed = [this]() {
        alert_sound_token_ = 0;
        next_alert_refresh_ = 0;
    };
}
void AirDisplay::QueueVolume(int value, std::function<void(int)> apply) {
    const uint32_t generation = ++volume_generation_;
    user_volume_ = value;
    Application::GetInstance().Schedule([this, value, generation, apply = std::move(apply)]() {
        if (apply)
            apply(value);
        applied_volume_generation_ = generation;
    });
}
int AirDisplay::DisplayVolume() const {
    // A slow NVS write from an older request must not pull the slider backwards.
    return volume_generation_ == applied_volume_generation_ ? volume_.load() : user_volume_.load();
}
AirDisplay::~AirDisplay() {
    DisplayLockGuard lock(this);
    if (!lock)
        return;
    if (timer_)
        lv_timer_delete(timer_);
    view_.reset();
}
void AirDisplay::SetupUI() {
    DisplayLockGuard lock(this);
    if (!lock || setup_ui_called_)
        return;
    view_ = std::make_unique<AirView>(state_, callbacks_);
    view_->Create(lv_display_get_screen_active(display_));
    setup_ui_called_ = true;
    timer_ = lv_timer_create(
        [](lv_timer_t* timer) { static_cast<AirDisplay*>(lv_timer_get_user_data(timer))->Tick(); },
        20, this);
    Tick();
}
void AirDisplay::ShowNotification(const char* text, int duration_ms) {
    DisplayLockGuard lock(this);
    if (!lock)
        return;
    // Upstream/remote messages cannot expand the UI or rely on an online glyph cache.
    char safe[96]{};
    size_t out = 0;
    const auto* p = reinterpret_cast<const unsigned char*>(text ? text : "");
    while (*p && out < sizeof(safe) - 5) {
        const auto* start = p;
        uint32_t code = *p++;
        const int extra = code < 0x80 ? 0 : code < 0xE0 ? 1 : code < 0xF0 ? 2 : 3;
        code &= extra == 0 ? 0x7F : extra == 1 ? 0x1F : extra == 2 ? 0x0F : 7;
        bool valid = extra == 0 || *start >= 0xC2;
        for (int i = 0; i < extra; ++i) {
            if ((*p & 0xC0) != 0x80) {
                valid = false;
                break;
            }
            code = (code << 6) | (*p++ & 0x3F);
        }
        lv_font_glyph_dsc_t glyph{};
        if (valid && code >= 32 && lv_font_get_glyph_dsc(&font_air_text_18, &glyph, code, 0) &&
            !glyph.is_placeholder) {
            const size_t bytes = p - start;
            std::memcpy(safe + out, start, bytes);
            out += bytes;
        } else
            safe[out++] = '?';
    }
    state_.Notify(safe, esp_timer_get_time() / 1000, duration_ms);
}
void AirDisplay::SetActivationCode(const std::string& code) {
    DisplayLockGuard lock(this);
    if (!lock)
        return;
    size_t n = 0;
    for (char c : code)
        if (c >= '0' && c <= '9' && n < activation_code_.size() - 1)
            activation_code_[n++] = c;
    activation_code_[n] = 0;
    state_.Notify("小智待激活，查看连接详情", esp_timer_get_time() / 1000, 10000);
}
void AirDisplay::SetTheme(Theme* theme) {
    if (!theme)
        return;
    DisplayLockGuard lock(this);
    if (!lock)
        return;
    current_theme_ = theme;
    const bool night = theme->name() == "dark";
    // Reapplying the current theme during an asset refresh preserves automatic mode.
    if (night != state_.night())
        state_.SetThemeMode(night ? ThemeMode::Night : ThemeMode::Day);
    RequestBrightness(state_.brightness());
    if (view_)
        view_->ApplyTheme();
    ++preferences_generation_;
}
void AirDisplay::SynchronizeSolar(std::optional<SolarLocation> location, int64_t utc_ms,
                                  uint64_t uptime_ms) {
    DisplayLockGuard lock(this);
    if (!lock || !solar_clock_.Synchronize(utc_ms, uptime_ms))
        return;
    if (location && location->valid() && *location != solar_clock_.location()) {
        solar_clock_.SetLocation(*location);
        ++preferences_generation_;
    }
    next_solar_refresh_ = 0;
}
void AirDisplay::UpdateAutoTheme(uint64_t now_ms) {
    if (state_.theme_mode() != ThemeMode::Auto) {
        next_solar_refresh_ = 0;
        return;
    }
    if (now_ms < next_solar_refresh_)
        return;
    next_solar_refresh_ = now_ms + 60000;
    const auto night = solar_clock_.Night(now_ms);
    if (!night || *night == state_.night())
        return;
    state_.SetTheme(*night);
    current_theme_ = LvglThemeManager::GetInstance().GetTheme(*night ? "dark" : "light");
    if (callbacks_.brightness)
        callbacks_.brightness(state_.brightness());
    else
        RequestBrightness(state_.brightness());
    if (view_)
        view_->ApplyTheme();
    ++preferences_generation_;
}
void AirDisplay::WakeHome() {
    requested_on_ = true;
    chat_requested_ = false;
    home_requested_ = true;
}
void AirDisplay::SetChatMessage(const char* role, const char* text) {
    DisplayLockGuard lock(this);
    if (lock && view_)
        view_->SetChatMessage(role, text);
}
void AirDisplay::RemoveChatMessage(const char* role, const char* text) {
    DisplayLockGuard lock(this);
    if (lock && view_)
        view_->RemoveChatMessage(role, text);
}
void AirDisplay::ToggleScreen() { requested_on_ = !requested_on_.load(); }
void AirDisplay::RequestDeviceAction(DeviceAction action) {
    DisplayLockGuard lock(this);
    if (lock && view_)
        view_->RequestAction(action);
}
bool AirDisplay::CommitPreferences(bool force) {
    if (!force && preferences_generation_ == saved_generation_)
        return true;
    if (!lvgl_port_lock(50))
        return false;
    const bool night = state_.night(), reduce = state_.reduce_motion, voice = state_.voice_enabled;
    const int day_level = state_.day_brightness(), night_level = state_.night_brightness();
    const int theme_mode = static_cast<int>(state_.theme_mode());
    const auto location = solar_clock_.location();
    const auto alerts = state_.alerts;
    const uint32_t generation = preferences_generation_;
    lvgl_port_unlock();
    if (GetStorageInitResult().available) {
        Settings prefs("air", true);
        prefs.SetBool("night", night);
        prefs.SetInt("theme_mode", theme_mode);
        if (location.valid()) {
            prefs.SetInt("solar_lat", location.latitude_e6);
            prefs.SetInt("solar_lon", location.longitude_e6);
        }
        prefs.SetBool("reduce_motion", reduce);
        prefs.SetBool("voice", voice);
        prefs.SetInt("day", day_level);
        prefs.SetInt("night_level", night_level);
        prefs.SetBool("alert_co2", alerts.co2_enabled);
        prefs.SetBool("alert_hcho", alerts.hcho_enabled);
        prefs.SetBool("alert_sound", alerts.sound);
        prefs.SetInt("co2_limit", alerts.co2_ppm);
        prefs.SetInt("hcho_limit", alerts.hcho_ppb);
    }
    // A failed/unavailable NVS cannot be repaired by delaying power-off indefinitely.
    saved_generation_ = generation;
    return true;
}
bool AirDisplay::FlushPreferences() { return CommitPreferences(true); }
void AirDisplay::SavePreferences() {
    if (preferences_generation_ == saved_generation_ || save_queued_.exchange(true))
        return;
    Application::GetInstance().Schedule([this]() {
        const bool saved = CommitPreferences(false);
        save_queued_ = false;
        if (saved)
            ShowNotification(GetStorageInitResult().available ? "已保存" : "保存失败，设置暂存",
                             2000);
    });
}
void AirDisplay::Tick() {
    const auto now = static_cast<uint64_t>(esp_timer_get_time() / 1000);
    const bool shutting_down = hardware_.IsShuttingDown();
    if (!shutting_down)
        UpdateAutoTheme(now);
    if (shutting_down)
        alert_sound_token_ = 0;
    const auto power = hardware_.Snapshot();
    // Concentration evaluation continues while the display is off.
    if (now >= next_alert_refresh_ || shutting_down) {
        next_alert_refresh_ = now + 100;
        const auto sample = sensors_.Snapshot();
        UpdateAlerts(sample, power);
    }
    const bool on = requested_on_.load();
    if (shutting_down && touch_)
        lv_indev_enable(touch_, false);
    if (on != state_.display_on() && esp_lcd_panel_disp_on_off(panel_, on) == ESP_OK) {
        state_.SetDisplayOn(on);
        hardware_.SetDisplayOn(on);
        if (touch_)
            lv_indev_enable(touch_, on && !shutting_down);
        if (!on)
            view_->StopAnimation();
        lv_display_enable_invalidation(display_, on);
        if (on) {
            lv_obj_invalidate(lv_display_get_screen_active(display_));
            next_refresh_ = 0;
        }
    }
    if (home_requested_.exchange(false))
        view_->WakeHome();
    if (chat_requested_.exchange(false) && !shutting_down)
        view_->ShowChat(true);
    const int user_brightness = user_brightness_.exchange(-1);
    if (user_brightness >= 0 && !shutting_down)
        view_->SetBrightness(user_brightness);
    const uint8_t brightness = brightness_.load();
    if (brightness != applied_brightness_) {
        const uint8_t data = (255 * std::min<uint8_t>(100, brightness)) / 100;
        if (esp_lcd_panel_io_tx_param(panel_io_, 0x02005100, &data, 1) == ESP_OK)
            applied_brightness_ = brightness;
    }
    if (!shutting_down)
        SavePreferences();
    const int volume = DisplayVolume();
    if (volume >= 0)
        view_->SetVolume(volume);
    if (!on || now < next_refresh_)
        return;
    next_refresh_ = now + 100;
    auto& wifi = WifiManager::GetInstance();
    auto device_state = Application::GetInstance().GetDeviceState();
    if (device_state == kDeviceStateWifiConfiguring && !wifi.IsConfigMode())
        device_state = kDeviceStateStarting;
    char connection[240];
    if (wifi.IsConfigMode())
        std::snprintf(connection, sizeof(connection), "配网热点：%s\n地址：%s",
                      wifi.GetApSsid().c_str(), wifi.GetApWebUrl().c_str());
    else if (device_state == kDeviceStateActivating && activation_code_[0])
        std::snprintf(connection, sizeof(connection), "小智激活码：%s\nxiaozhi.me",
                      activation_code_.data());
    else
        std::snprintf(connection, sizeof(connection), "Wi-Fi %s\nUSB %s",
                      wifi.IsConnected() ? "已连接" : "离线",
                      hardware_.Snapshot().vbus ? "已连接" : "未连接");
    current_theme_ = LvglThemeManager::GetInstance().GetTheme(state_.night() ? "dark" : "light");
    view_->Refresh(sensors_.Snapshot(), hardware_.Snapshot(), device_state, wifi.IsConnected(),
                   GetStorageInitResult().available, connection);
}
void AirDisplay::UpdateAlerts(const AirSnapshot& sample, const PowerSnapshot& power) {
    if (power.shutting_down) {
        alert_sound_token_ = 0;
        view_->SetAlerts({}, sample, power);
        return;
    }
    const auto alerts = alert_policy_.Update(sample, state_.alerts);
    alert_sound_token_ = alerts.pending && state_.alerts.sound ? alerts.generation : 0;
    view_->SetAlerts(alerts, sample, power);
    if (alerts.pending && alerts.generation != sounded_alert_generation_) {
        sounded_alert_generation_ = alerts.generation;
        if (state_.alerts.sound && callbacks_.alert_sound)
            callbacks_.alert_sound(alerts.generation);
    }
}
}  // namespace air
