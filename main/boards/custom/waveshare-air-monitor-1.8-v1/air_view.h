#pragma once
#include <lvgl.h>
#include <array>
#include <ctime>
#include <functional>
#include <memory>
#include <vector>
#include "air_chat_view.h"
#include "air_controls.h"
#include "air_types.h"
#include "air_ui_state.h"

namespace air {
struct AirViewCallbacks {
    std::function<uint64_t()> now_ms;
    std::function<std::time_t()> wall_time;
    std::function<void()> voice;
    std::function<void()> stop_voice;
    std::function<void(int)> brightness;
    std::function<void(int)> volume;
    std::function<void(uint32_t)> acknowledge_alert;
    std::function<void(uint32_t)> alert_sound;
    std::function<void()> alerts_changed;
    std::function<void()> preferences;
    std::function<void(bool)> voice_enabled;
    std::function<void(DeviceAction)> confirmed_action;
    std::function<void()> cancel_config;
    std::function<void(Metric, std::array<HistoryPoint, kHistorySize>&)> history;
};
class AirView {
public:
    AirView(AirUiState& state, AirViewCallbacks callbacks)
        : state_(state), callbacks_(std::move(callbacks)) {}
    ~AirView();
    void Create(lv_obj_t* screen);
    void Refresh(const AirSnapshot& snapshot, const PowerSnapshot& power, DeviceState device_state,
                 bool connected, bool storage_available, const char* connection_info);
    void Navigate(Page page, bool animate = true);
    void WakeHome();
    void ApplyTheme();
    void SetBrightness(int percent);
    void SetVolume(int percent);
    void RequestAction(DeviceAction action);
    void StopAnimation();
    void SetAlerts(const AlertSnapshot& alerts, const AirSnapshot& sample,
                   const PowerSnapshot& power);
    void ShowChat(bool voice_intent = false);
    void SetChatMessage(const char* role, const char* content);
    void RemoveChatMessage(const char* role, const char* content);
    bool ChatVisible() const { return chat_view_ && chat_view_->visible(); }

private:
    struct Palette {
        uint32_t bg, text, muted, accent, lime, border, soft;
    };
    lv_obj_t* Box(lv_obj_t* parent, int x, int y, int w, int h, int radius = 0);
    lv_obj_t* Label(lv_obj_t* parent, const char* text, int x, int y, int width,
                    const lv_font_t* font, bool secondary = false);
    lv_obj_t* Button(lv_obj_t* parent, const char* text, int x, int y, int w, int h,
                     bool icon = false);
    void CreateHeader(lv_obj_t* page, int index);
    void UpdateHeader();
    void CreateHome();
    void CreateTrend();
    void CreateSettings();
    void CreateDrawer();
    void CreateConfirmation();
    void CreateAlertSettings();
    void RefreshAlertSettings();
    void UpdateHome();
    void UpdateTrend();
    uint32_t ReadingColor(Metric metric, bool inverted = false) const;
    void UpdateFooter();
    void UpdateDrawer(const char* connection_info);
    void RefreshSettings();
    void UpdateVolumeText();
    void Handle(lv_event_t* event);
    void HandleTouch(lv_event_t* event);
    void SetTransition(int32_t progress);
    void AnimateTransition(int from, int to);
    void NormalizePages();
    uint64_t Now() const;
    static void Event(lv_event_t* event);
    static void FilterSliderTouch(lv_event_t* event);
    static void Touch(lv_event_t* event);
    AirUiState& state_;
    AirViewCallbacks callbacks_;
    Palette palette_{};
    AirSnapshot sample_;
    PowerSnapshot power_;
    DeviceState device_state_ = kDeviceStateStarting;
    bool connected_ = false;
    bool storage_available_ = true;
    bool listening_ = false;
    bool last_night_ = false;
    bool settings_refresh_ = false;
    Metric metric_ = Metric::Co2;
    uint64_t last_chart_bucket_ = UINT64_MAX;
    uint64_t last_sample_ms_ = UINT64_MAX;
    uint64_t confirmation_id_ = 0;
    uint64_t confirmation_until_ = 0;
    ActionGate action_gate_;
    AlertSnapshot alerts_;
    std::unique_ptr<AirChatView> chat_view_;
    bool alert_settings_open_ = false;
    std::array<HistoryPoint, kHistorySize> history_{};
    std::vector<lv_obj_t*> primary_, secondary_, inverted_, round_buttons_, surfaces_, rules_;
    lv_obj_t* root_ = nullptr;
    lv_obj_t* toast_ = nullptr;
    lv_obj_t* toast_text_ = nullptr;
    lv_obj_t* decoration_ = nullptr;
    lv_obj_t* pages_[3]{};
    lv_obj_t* clocks_[3]{};
    lv_obj_t* wifi_icons_[3]{};
    lv_obj_t* status_ = nullptr;
    lv_obj_t* status_pill_ = nullptr;
    lv_obj_t* sample_dot_ = nullptr;
    lv_obj_t* co2_ = nullptr;
    lv_obj_t* co2_age_ = nullptr;
    lv_obj_t* hcho_card_ = nullptr;
    lv_obj_t* hcho_ = nullptr;
    lv_obj_t* hcho_status_ = nullptr;
    lv_obj_t* temperature_ = nullptr;
    lv_obj_t* humidity_ = nullptr;
    lv_obj_t* mic_ = nullptr;
    lv_obj_t* mic_text_ = nullptr;
    lv_obj_t* shortcut_ = nullptr;
    lv_obj_t* shortcut_icon_ = nullptr;
    lv_obj_t* dots_[3]{};
    lv_obj_t* back_[2]{};
    lv_obj_t* selector_[2]{};
    lv_obj_t* trend_value_ = nullptr;
    lv_obj_t* trend_unit_ = nullptr;
    lv_obj_t* trend_age_ = nullptr;
    lv_obj_t* chart_ = nullptr;
    lv_chart_series_t* series_ = nullptr;
    lv_obj_t* chart_empty_ = nullptr;
    lv_obj_t* axis_min_ = nullptr;
    lv_obj_t* axis_max_ = nullptr;
    lv_obj_t* slider_ = nullptr;
    lv_obj_t* brightness_text_ = nullptr;
    lv_obj_t* volume_slider_ = nullptr;
    lv_obj_t* volume_text_ = nullptr;
    bool volume_dragging_ = false, volume_changed_ = false;
    lv_point_t slider_touch_start_{};
    lv_obj_t* theme_buttons_[3]{};
    lv_obj_t* motion_switch_ = nullptr;
    lv_obj_t* voice_switch_ = nullptr;
    lv_obj_t* detail_button_ = nullptr;
    lv_obj_t* alert_button_ = nullptr;
    lv_obj_t* alert_settings_ = nullptr;
    lv_obj_t* alert_settings_back_ = nullptr;
    lv_obj_t* co2_alert_switch_ = nullptr;
    lv_obj_t* hcho_alert_switch_ = nullptr;
    lv_obj_t* alert_sound_switch_ = nullptr;
    lv_obj_t* co2_limit_slider_ = nullptr;
    lv_obj_t* hcho_limit_slider_ = nullptr;
    lv_obj_t* co2_limit_text_ = nullptr;
    lv_obj_t* hcho_limit_text_ = nullptr;
    lv_obj_t* drawer_ = nullptr;
    lv_obj_t* drawer_panel_ = nullptr;
    lv_obj_t* drawer_text_ = nullptr;
    lv_obj_t* drawer_close_ = nullptr;
    lv_obj_t* wifi_button_ = nullptr;
    lv_obj_t* shutdown_button_ = nullptr;
    lv_obj_t* confirmation_ = nullptr;
    lv_obj_t* confirmation_panel_ = nullptr;
    lv_obj_t* confirmation_title_ = nullptr;
    lv_obj_t* confirmation_body_ = nullptr;
    lv_obj_t* confirm_button_ = nullptr;
    lv_obj_t* cancel_button_ = nullptr;
    lv_point_t touch_start_{};
    bool touch_eligible_ = false;
    bool dragging_ = false;
    int transition_from_ = 0, transition_to_ = 0, transition_dir_ = 1;
    int drag_progress_ = 0;
};
}  // namespace air
