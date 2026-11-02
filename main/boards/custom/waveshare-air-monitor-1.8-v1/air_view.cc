#include "air_view.h"
#include <material_symbols.h>
#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstring>
#include "air_clock.h"
#include "air_fonts.h"

LV_FONT_DECLARE(font_material_symbols_20_4);
LV_FONT_DECLARE(font_material_symbols_30_4);
namespace air {
namespace {
constexpr int kWidth = 368;
constexpr lv_style_selector_t kCheckedIndicator =
    static_cast<lv_style_selector_t>(LV_PART_INDICATOR) |
    static_cast<lv_style_selector_t>(LV_STATE_CHECKED);
void Text(lv_obj_t* label, const char* text) {
    if (std::strcmp(lv_label_get_text(label), text) != 0)
        lv_label_set_text(label, text);
}
void TextColor(lv_obj_t* label, uint32_t color) {
    if (!lv_color_eq(lv_obj_get_style_text_color(label, LV_PART_MAIN), lv_color_hex(color)))
        lv_obj_set_style_text_color(label, lv_color_hex(color), 0);
}
void Background(lv_obj_t* object, uint32_t color) {
    if (!lv_color_eq(lv_obj_get_style_bg_color(object, LV_PART_MAIN), lv_color_hex(color)))
        lv_obj_set_style_bg_color(object, lv_color_hex(color), 0);
}
bool HasDisplayValue(const AirSnapshot& sample, Metric metric) {
    const auto& channel = metric == Metric::Co2 ? sample.co2 : sample.hcho;
    return channel.has_value && channel.connected &&
           (metric == Metric::Co2
                ? sample.scd.ppm != 0
                : std::isfinite(sample.sfa.ppb) && sample.sfa.ppb >= 0 && sample.sfa.ppb <= 2000);
}
const char* Status(const ChannelState& channel, bool hcho) {
    if (!channel.connected)
        return channel.errors >= 3 ? "未连接" : "等待采样";
    if (!channel.ready)
        return hcho ? "预热中" : "等待采样";
    if (channel.stale)
        return "已过期";
    if (channel.errors >= 3)
        return "读取异常";
    if (!channel.environment_ok)
        return "超出额定条件";
    if (!channel.within_spec)
        return hcho ? "稳定中" : "超量程";
    return "已就绪";
}
void Age(char* text, size_t size, const ChannelState& channel, uint64_t now) {
    if (!channel.has_value) {
        std::snprintf(text, size, "%s", "等待采样");
        return;
    }
    const auto seconds = (now - std::min(now, channel.last_value_ms)) / 1000;
    if (seconds == 0)
        std::snprintf(text, size, "%s", "刚刚更新");
    else if (seconds < 60)
        std::snprintf(text, size, "%llu秒前更新", static_cast<unsigned long long>(seconds));
    else
        std::snprintf(text, size, "%llu分钟前更新", static_cast<unsigned long long>(seconds / 60));
}
void Hidden(lv_obj_t* object, bool hidden) {
    if (hidden)
        lv_obj_add_flag(object, LV_OBJ_FLAG_HIDDEN);
    else
        lv_obj_remove_flag(object, LV_OBJ_FLAG_HIDDEN);
}
}  // namespace
uint64_t AirView::Now() const { return callbacks_.now_ms ? callbacks_.now_ms() : sample_.now_ms; }
uint32_t AirView::ReadingColor(Metric metric, bool inverted) const {
    const bool hcho = metric == Metric::Hcho;
    const auto& channel = hcho ? sample_.hcho : sample_.co2;
    const auto muted = inverted ? 0xADBEAF : palette_.muted;
    if (!HasDisplayValue(sample_, metric) || !channel.has_frame || !channel.ready ||
        channel.stale || channel.errors != 0 || !channel.environment_ok ||
        channel.last_frame_ms != channel.last_value_ms || channel.last_value_ms > sample_.now_ms ||
        sample_.now_ms - channel.last_value_ms > (hcho ? 5000 : 15000) ||
        !std::isfinite(hcho ? sample_.sfa.temperature : sample_.scd.temperature) ||
        !std::isfinite(hcho ? sample_.sfa.humidity : sample_.scd.humidity))
        return muted;
    if (hcho ? (!channel.within_spec || !sample_.sfa.ready || !sample_.sfa.within_spec ||
                (sample_.sfa.status & 3) != 0)
             : sample_.scd.ppm < 400 || (!channel.within_spec && sample_.scd.ppm <= 5000))
        return muted;
    // Use the displayed integer ppb. Source limits and averaging periods are in
    // doc/浓度读数颜色分级.md; these bands do not change the alarm settings.
    const auto value = hcho ? std::lround(sample_.sfa.ppb) : sample_.scd.ppm;
    const bool dark = inverted || state_.night();
    if (value >= (hcho ? 80 : 2000))
        return dark ? 0xFFBFC5 : 0xBB3038;
    if (value >= (hcho ? 65 : 1000))
        return dark ? 0xFFDA75 : 0x936200;
    return inverted ? 0xF1FAEE : palette_.text;
}
AirView::~AirView() {
    StopAnimation();
    chat_view_.reset();
    if (root_)
        lv_obj_delete(root_);
}
lv_obj_t* AirView::Box(lv_obj_t* parent, int x, int y, int w, int h, int radius) {
    auto* object = lv_obj_create(parent);
    lv_obj_remove_style_all(object);
    lv_obj_set_pos(object, x, y);
    lv_obj_set_size(object, w, h);
    lv_obj_set_style_radius(object, radius, 0);
    lv_obj_remove_flag(object, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_remove_flag(object, LV_OBJ_FLAG_CLICKABLE);
    return object;
}
lv_obj_t* AirView::Label(lv_obj_t* parent, const char* text, int x, int y, int width,
                         const lv_font_t* font, bool secondary) {
    auto* label = lv_label_create(parent);
    lv_obj_remove_style_all(label);
    lv_obj_set_pos(label, x, y);
    lv_obj_set_width(label, width);
    lv_label_set_long_mode(label, LV_LABEL_LONG_WRAP);
    lv_obj_set_style_text_font(label, font, 0);
    lv_label_set_text(label, text);
    (secondary ? secondary_ : primary_).push_back(label);
    return label;
}
lv_obj_t* AirView::Button(lv_obj_t* parent, const char* text, int x, int y, int w, int h,
                          bool icon) {
    auto* button = Box(parent, x, y, w, h, w == h ? w / 2 : 12);
    lv_obj_add_flag(button, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_remove_flag(button, LV_OBJ_FLAG_GESTURE_BUBBLE);
    lv_obj_set_style_bg_opa(button, LV_OPA_COVER, 0);
    lv_obj_set_style_bg_opa(button, LV_OPA_70, LV_STATE_PRESSED);
    lv_obj_set_style_transform_scale(button, 244, LV_STATE_PRESSED);
    auto* label =
        Label(button, text, 0, 0, w, icon ? &font_material_symbols_30_4 : &font_air_text_18);
    lv_obj_set_style_text_align(label, LV_TEXT_ALIGN_CENTER, 0);
    lv_obj_center(label);
    lv_obj_add_event_cb(button, Event, LV_EVENT_ALL, this);
    round_buttons_.push_back(button);
    return button;
}
void AirView::Create(lv_obj_t* screen) {
    if (root_)
        return;
    root_ = Box(screen, 0, 0, 368, 448);
    lv_obj_set_style_bg_opa(root_, LV_OPA_COVER, 0);
    decoration_ = Box(root_, 282, -116, 252, 252, 126);
    for (auto& page : pages_) {
        page = Box(root_, 0, 0, 368, 392);
        lv_obj_add_flag(page, LV_OBJ_FLAG_CLICKABLE);
        lv_obj_add_event_cb(page, Touch, LV_EVENT_ALL, this);
    }
    CreateHome();
    CreateTrend();
    CreateSettings();
    mic_ = Button(root_, MATERIAL_SYMBOLS_MIC, 16, 396, 48, 48, true);
    mic_text_ = Label(root_, "语音离线", 72, 410, 90, &font_air_text_18);
    shortcut_ = Button(root_, MATERIAL_SYMBOLS_SETTINGS, 304, 396, 48, 48, true);
    shortcut_icon_ = lv_obj_get_child(shortcut_, 0);
    for (int i = 0; i < 3; ++i) {
        dots_[i] = Box(root_, 170 + i * 16, 419, 8, 8, 4);
        lv_obj_set_style_bg_opa(dots_[i], LV_OPA_COVER, 0);
    }
    AirChatView::Callbacks chat_callbacks;
    chat_callbacks.now_ms = callbacks_.now_ms;
    chat_callbacks.back = [this]() { Navigate(Page::Home, false); };
    chat_callbacks.start = [this]() {
        if (device_state_ == kDeviceStateIdle && connected_ && state_.voice_enabled &&
            callbacks_.voice)
            callbacks_.voice();
    };
    chat_callbacks.stop = callbacks_.stop_voice;
    chat_view_ = std::make_unique<AirChatView>(std::move(chat_callbacks));
    chat_view_->Create(root_);
    CreateDrawer();
    CreateConfirmation();
    CreateAlertSettings();
    toast_ = Box(root_, 16, 338, 336, 32, 16);
    lv_obj_set_style_bg_opa(toast_, LV_OPA_COVER, 0);
    toast_text_ = Label(toast_, "", 12, 5, 312, &font_air_text_18);
    lv_obj_set_height(toast_text_, 22);
    lv_label_set_long_mode(toast_text_, LV_LABEL_LONG_DOT);
    lv_obj_set_style_text_align(toast_text_, LV_TEXT_ALIGN_CENTER, 0);
    Hidden(toast_, true);
    ApplyTheme();
    NormalizePages();
    RefreshSettings();
}
void AirView::CreateHeader(lv_obj_t* page, int index) {
    const bool home = index == 0;
    clocks_[index] = Label(page, "--:--", home ? 24 : 216, home ? 24 : 25, home ? 124 : 100,
                           home ? &font_air_text_20 : &font_air_text_18);
    lv_obj_set_height(clocks_[index], 26);
    lv_label_set_long_mode(clocks_[index], LV_LABEL_LONG_CLIP);
    wifi_icons_[index] =
        Label(page, MATERIAL_SYMBOLS_WIFI_OFF, 322, 24, 22, &font_material_symbols_20_4);
    lv_obj_set_height(wifi_icons_[index], 22);
    lv_label_set_long_mode(wifi_icons_[index], LV_LABEL_LONG_CLIP);
    lv_obj_set_style_text_align(wifi_icons_[index], LV_TEXT_ALIGN_CENTER, 0);
}
void AirView::UpdateHeader() {
    const auto clock = FormatLocalClock(callbacks_.wall_time ? callbacks_.wall_time() : 0);
    for (int i = 0; i < 3; ++i) {
        Text(clocks_[i], clock.data());
        Text(wifi_icons_[i], connected_ ? MATERIAL_SYMBOLS_WIFI : MATERIAL_SYMBOLS_WIFI_OFF);
        TextColor(wifi_icons_[i], connected_ ? palette_.text : palette_.muted);
    }
}
void AirView::CreateHome() {
    auto* page = pages_[0];
    CreateHeader(page, 0);
    status_pill_ = Box(page, 160, 20, 136, 30, 15);
    surfaces_.push_back(status_pill_);
    status_ = Label(status_pill_, "等待采样", 0, 4, 136, &font_air_text_18);
    lv_obj_set_style_text_align(status_, LV_TEXT_ALIGN_CENTER, 0);
    Label(page, "CO₂", 24, 90, 120, &font_air_text_20);
    Label(page, "二氧化碳", 240, 94, 108, &font_air_text_18, true);
    sample_dot_ = Box(page, 224, 102, 6, 6, 3);
    lv_obj_set_style_bg_opa(sample_dot_, LV_OPA_COVER, 0);
    co2_ = Label(page, "—", 22, 132, 252, &font_air_digits_120);
    lv_obj_set_height(co2_, 96);
    lv_label_set_long_mode(co2_, LV_LABEL_LONG_CLIP);
    auto* unit = Box(page, 282, 200, 62, 32, 16);
    lv_obj_set_style_bg_color(unit, lv_color_hex(0x146B55), 0);
    lv_obj_set_style_bg_opa(unit, LV_OPA_COVER, 0);
    auto* ppm = Label(unit, "ppm", 0, 4, 62, &font_air_text_18);
    inverted_.push_back(ppm);
    lv_obj_set_style_text_align(ppm, LV_TEXT_ALIGN_CENTER, 0);
    co2_age_ = Label(page, "等待采样", 24, 229, 320, &font_air_text_18, true);
    lv_obj_set_height(co2_age_, 22);
    lv_label_set_long_mode(co2_age_, LV_LABEL_LONG_DOT);
    hcho_card_ = Box(page, 16, 260, 336, 94, 20);
    lv_obj_set_style_bg_opa(hcho_card_, LV_OPA_COVER, 0);
    lv_obj_set_style_bg_grad_dir(hcho_card_, LV_GRAD_DIR_HOR, 0);
    lv_obj_set_style_border_width(hcho_card_, 1, 0);
    auto* marker = Box(hcho_card_, 14, 0, 28, 5, 3);
    lv_obj_set_style_bg_color(marker, lv_color_hex(0xC6EF87), 0);
    lv_obj_set_style_bg_opa(marker, LV_OPA_COVER, 0);
    inverted_.push_back(Label(hcho_card_, "甲醛", 20, 24, 112, &font_air_text_20));
    hcho_status_ = Label(hcho_card_, "等待采样", 20, 51, 112, &font_air_text_18);
    lv_obj_set_height(hcho_status_, 21);
    lv_label_set_long_mode(hcho_status_, LV_LABEL_LONG_CLIP);
    inverted_.push_back(hcho_status_);
    hcho_ = Label(hcho_card_, "—", 140, 23, 132, &font_air_digits_64);
    lv_obj_set_height(hcho_, 47);
    lv_label_set_long_mode(hcho_, LV_LABEL_LONG_CLIP);
    lv_obj_set_style_text_align(hcho_, LV_TEXT_ALIGN_RIGHT, 0);
    inverted_.push_back(hcho_);
    inverted_.push_back(Label(hcho_card_, "ppb", 282, 53, 44, &font_air_text_18));
    Label(page, MATERIAL_SYMBOLS_DEVICE_THERMOSTAT, 22, 362, 30, &font_material_symbols_30_4);
    temperature_ = Label(page, "—", 58, 369, 114, &font_air_digits_28);
    auto* divider = Box(page, 183, 366, 1, 26);
    rules_.push_back(divider);
    auto* drop = lv_line_create(page);
    static const lv_point_precise_t drop_points[] = {{11, 0},  {3, 12},  {1, 17},  {2, 23},
                                                     {6, 27},  {11, 28}, {16, 27}, {20, 23},
                                                     {21, 17}, {19, 12}, {11, 0}};
    lv_line_set_points(drop, drop_points, sizeof(drop_points) / sizeof(drop_points[0]));
    lv_obj_set_pos(drop, 205, 362);
    lv_obj_set_style_line_width(drop, 2, 0);
    rules_.push_back(drop);
    humidity_ = Label(page, "—", 240, 369, 104, &font_air_digits_28);
}
void AirView::CreateTrend() {
    auto* page = pages_[1];
    CreateHeader(page, 1);
    back_[0] = Button(page, MATERIAL_SYMBOLS_ARROW_BACK, 8, 12, 48, 48, true);
    Label(page, "历史曲线", 66, 24, 132, &font_air_text_20);
    selector_[0] = Button(page, "CO₂", 24, 76, 156, 48);
    selector_[1] = Button(page, "甲醛 HCHO", 188, 76, 156, 48);
    Label(page, "当前", 24, 137, 80, &font_air_text_18, true);
    trend_value_ = Label(page, "—", 24, 166, 132, &font_air_digits_42);
    trend_unit_ = Label(page, "ppm", 164, 180, 60, &font_air_text_18, true);
    trend_age_ = Label(page, "等待采样", 24, 204, 320, &font_air_text_18, true);
    chart_ = lv_chart_create(page);
    lv_obj_remove_style_all(chart_);
    lv_obj_set_pos(chart_, 66, 246);
    lv_obj_set_size(chart_, 278, 108);
    lv_obj_set_style_line_width(chart_, 2, LV_PART_ITEMS);
    lv_obj_set_style_size(chart_, 0, 0, LV_PART_INDICATOR);
    lv_obj_set_style_line_width(chart_, 1, LV_PART_MAIN);
    // Scatter's line renderer preserves every gap at subpixel X spacing; LINE
    // enters a min/max compression mode when 360 samples exceed the plot width.
    lv_chart_set_type(chart_, LV_CHART_TYPE_SCATTER);
    lv_chart_set_point_count(chart_, kHistorySize);
    lv_chart_set_axis_range(chart_, LV_CHART_AXIS_PRIMARY_X, 0, kHistorySize - 1);
    lv_chart_set_div_line_count(chart_, 3, 4);
    lv_obj_remove_flag(chart_, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_remove_flag(chart_, LV_OBJ_FLAG_SCROLLABLE);
    series_ = lv_chart_add_series(chart_, lv_color_hex(0x146B55), LV_CHART_AXIS_PRIMARY_Y);
    axis_max_ = Label(page, "1000", 16, 238, 46, &font_air_text_18, true);
    axis_min_ = Label(page, "0", 16, 337, 46, &font_air_text_18, true);
    Label(page, "30分钟前", 66, 361, 140, &font_air_text_18, true);
    auto* now = Label(page, "现在", 286, 361, 58, &font_air_text_18, true);
    lv_obj_set_style_text_align(now, LV_TEXT_ALIGN_RIGHT, 0);
    chart_empty_ = Label(page, "等待有效数据", 72, 282, 264, &font_air_text_18, true);
    lv_obj_set_style_text_align(chart_empty_, LV_TEXT_ALIGN_CENTER, 0);
}
void AirView::CreateSettings() {
    auto* page = pages_[2];
    CreateHeader(page, 2);
    back_[1] = Button(page, MATERIAL_SYMBOLS_ARROW_BACK, 8, 12, 48, 48, true);
    Label(page, "设置", 66, 24, 132, &font_air_text_20);
    auto* body = Box(page, 16, 76, 336, 312);
    lv_obj_add_flag(body, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_add_flag(body, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_set_scroll_dir(body, LV_DIR_VER);
    lv_obj_set_scrollbar_mode(body, LV_SCROLLBAR_MODE_AUTO);
    lv_obj_remove_flag(body, LV_OBJ_FLAG_GESTURE_BUBBLE);
    auto* light = Box(body, 0, 0, 336, 80, 16);
    surfaces_.push_back(light);
    Label(light, "亮度", 16, 10, 100, &font_air_text_20);
    brightness_text_ = Label(light, "70%", 248, 12, 72, &font_air_text_18);
    lv_obj_set_style_text_align(brightness_text_, LV_TEXT_ALIGN_RIGHT, 0);
    slider_ = lv_slider_create(light);
    lv_obj_set_pos(slider_, 20, 54);
    lv_obj_set_size(slider_, 296, 6);
    lv_obj_set_ext_click_area(slider_, 21);
    lv_slider_set_range(slider_, 1, 100);
    lv_obj_remove_flag(slider_, LV_OBJ_FLAG_GESTURE_BUBBLE);
    lv_obj_add_event_cb(slider_, FilterSliderTouch,
                        static_cast<lv_event_code_t>(LV_EVENT_ALL | LV_EVENT_PREPROCESS), this);
    lv_obj_add_event_cb(slider_, Event, LV_EVENT_ALL, this);
    auto* sound = Box(body, 0, 92, 336, 80, 16);
    surfaces_.push_back(sound);
    Label(sound, "音量", 16, 10, 100, &font_air_text_20);
    volume_text_ = Label(sound, "70%", 228, 12, 92, &font_air_text_18);
    lv_obj_set_style_text_align(volume_text_, LV_TEXT_ALIGN_RIGHT, 0);
    volume_slider_ = lv_slider_create(sound);
    lv_obj_set_pos(volume_slider_, 20, 54);
    lv_obj_set_size(volume_slider_, 296, 6);
    lv_obj_set_ext_click_area(volume_slider_, 21);
    lv_slider_set_range(volume_slider_, 0, 100);
    lv_slider_set_value(volume_slider_, 70, LV_ANIM_OFF);
    lv_obj_remove_flag(volume_slider_, LV_OBJ_FLAG_GESTURE_BUBBLE);
    lv_obj_add_event_cb(volume_slider_, FilterSliderTouch,
                        static_cast<lv_event_code_t>(LV_EVENT_ALL | LV_EVENT_PREPROCESS), this);
    lv_obj_add_event_cb(volume_slider_, Event, LV_EVENT_ALL, this);
    Label(body, "主题", 16, 194, 80, &font_air_text_20);
    theme_buttons_[0] = Button(body, "日间", 112, 184, 64, 48);
    theme_buttons_[1] = Button(body, "夜间", 184, 184, 64, 48);
    theme_buttons_[2] = Button(body, "自动", 256, 184, 64, 48);
    Label(body, "减少动态", 16, 250, 180, &font_air_text_20);
    motion_switch_ = lv_switch_create(body);
    lv_obj_set_pos(motion_switch_, 270, 247);
    lv_obj_set_size(motion_switch_, 48, 28);
    lv_obj_set_ext_click_area(motion_switch_, 10);
    lv_obj_remove_flag(motion_switch_, LV_OBJ_FLAG_GESTURE_BUBBLE);
    lv_obj_add_event_cb(motion_switch_, Event, LV_EVENT_ALL, this);
    Label(body, "小智语音", 16, 306, 180, &font_air_text_20);
    voice_switch_ = lv_switch_create(body);
    lv_obj_set_pos(voice_switch_, 270, 303);
    lv_obj_set_size(voice_switch_, 48, 28);
    lv_obj_set_ext_click_area(voice_switch_, 10);
    lv_obj_remove_flag(voice_switch_, LV_OBJ_FLAG_GESTURE_BUBBLE);
    lv_obj_add_event_cb(voice_switch_, Event, LV_EVENT_ALL, this);
    alert_button_ = Button(body, "浓度提醒  ›", 0, 352, 336, 48);
    detail_button_ = Button(body, "传感器与连接  ›", 0, 408, 336, 48);
}
void AirView::CreateAlertSettings() {
    alert_settings_ = Box(root_, 0, 0, 368, 448);
    lv_obj_add_flag(alert_settings_, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_set_style_bg_opa(alert_settings_, LV_OPA_COVER, 0);
    alert_settings_back_ =
        Button(alert_settings_, MATERIAL_SYMBOLS_ARROW_BACK, 8, 12, 48, 48, true);
    Label(alert_settings_, "浓度提醒", 66, 24, 240, &font_air_text_20);
    Label(alert_settings_, "持续30秒偏高才提醒", 24, 66, 320, &font_air_text_18, true);
    for (int i = 0; i < 2; ++i) {
        auto* card = Box(alert_settings_, 16, 100 + i * 118, 336, 106, 16);
        surfaces_.push_back(card);
        Label(card, i == 0 ? "CO₂" : "甲醛 HCHO", 16, 12, 210, &font_air_text_20);
        auto*& toggle = i == 0 ? co2_alert_switch_ : hcho_alert_switch_;
        toggle = lv_switch_create(card);
        lv_obj_set_pos(toggle, 270, 12);
        lv_obj_set_size(toggle, 48, 28);
        lv_obj_set_ext_click_area(toggle, 10);
        lv_obj_add_event_cb(toggle, Event, LV_EVENT_ALL, this);
        auto*& value = i == 0 ? co2_limit_text_ : hcho_limit_text_;
        value = Label(card, "", 16, 61, 116, &font_air_text_18);
        auto*& slider = i == 0 ? co2_limit_slider_ : hcho_limit_slider_;
        slider = lv_slider_create(card);
        lv_obj_set_pos(slider, 142, 72);
        lv_obj_set_size(slider, 174, 6);
        lv_obj_set_ext_click_area(slider, 20);
        lv_slider_set_range(slider, i == 0 ? 600 : 20, i == 0 ? 5000 : 500);
        lv_obj_add_event_cb(slider, Event, LV_EVENT_ALL, this);
    }
    Label(alert_settings_, "提示音", 24, 342, 190, &font_air_text_20);
    alert_sound_switch_ = lv_switch_create(alert_settings_);
    lv_obj_set_pos(alert_sound_switch_, 286, 341);
    lv_obj_set_size(alert_sound_switch_, 48, 28);
    lv_obj_set_ext_click_area(alert_sound_switch_, 10);
    lv_obj_add_event_cb(alert_sound_switch_, Event, LV_EVENT_ALL, this);
    Label(alert_settings_, "遵守当前音量和静音", 24, 376, 320, &font_air_text_18, true);
    Hidden(alert_settings_, true);
}
void AirView::RefreshAlertSettings() {
    if (!alert_settings_)
        return;
    const bool refreshing = settings_refresh_;
    settings_refresh_ = true;
    state_.alerts = AirAlertPolicy::NormalizeSettings(state_.alerts);
    for (int i = 0; i < 2; ++i) {
        auto* toggle = i == 0 ? co2_alert_switch_ : hcho_alert_switch_;
        const bool enabled = i == 0 ? state_.alerts.co2_enabled : state_.alerts.hcho_enabled;
        if (enabled)
            lv_obj_add_state(toggle, LV_STATE_CHECKED);
        else
            lv_obj_remove_state(toggle, LV_STATE_CHECKED);
        auto* slider = i == 0 ? co2_limit_slider_ : hcho_limit_slider_;
        const int value = i == 0 ? state_.alerts.co2_ppm : state_.alerts.hcho_ppb;
        if (lv_slider_get_value(slider) != value)
            lv_slider_set_value(slider, value, LV_ANIM_OFF);
        char text[32];
        std::snprintf(text, sizeof(text), i == 0 ? "%d ppm" : "%d ppb", value);
        Text(i == 0 ? co2_limit_text_ : hcho_limit_text_, text);
    }
    if (state_.alerts.sound)
        lv_obj_add_state(alert_sound_switch_, LV_STATE_CHECKED);
    else
        lv_obj_remove_state(alert_sound_switch_, LV_STATE_CHECKED);
    settings_refresh_ = refreshing;
}
void AirView::SetAlerts(const AlertSnapshot& alerts, const AirSnapshot&,
                        const PowerSnapshot& power) {
    alerts_ = alerts;
    power_ = power;
    if (state_.page() == Page::Home && state_.display_on())
        UpdateHome();
}
void AirView::ShowChat(bool voice_intent) {
    if (!chat_view_ || power_.shutting_down)
        return;
    StopAnimation();
    state_.SetDrawer(false);
    Hidden(drawer_, true);
    alert_settings_open_ = false;
    Hidden(alert_settings_, true);
    chat_view_->Open(Now(), voice_intent);
}
void AirView::SetChatMessage(const char* role, const char* content) {
    if (chat_view_)
        chat_view_->Append(role, content);
}
void AirView::RemoveChatMessage(const char* role, const char* content) {
    if (chat_view_)
        chat_view_->Remove(role, content);
}
void AirView::CreateDrawer() {
    drawer_ = Box(root_, 0, 0, 368, 448);
    lv_obj_add_flag(drawer_, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_set_style_bg_color(drawer_, lv_color_black(), 0);
    lv_obj_set_style_bg_opa(drawer_, LV_OPA_50, 0);
    drawer_panel_ = Box(drawer_, 8, 44, 352, 396, 20);
    surfaces_.push_back(drawer_panel_);
    Label(drawer_panel_, "传感器与连接", 16, 20, 256, &font_air_text_20);
    drawer_close_ = Button(drawer_panel_, MATERIAL_SYMBOLS_CLOSE, 296, 8, 48, 48, true);
    auto* scroll = Box(drawer_panel_, 16, 66, 320, 248);
    lv_obj_add_flag(scroll, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_scroll_dir(scroll, LV_DIR_VER);
    drawer_text_ = Label(scroll, "等待采样", 0, 0, 310, &font_air_text_18);
    lv_obj_set_style_text_line_space(drawer_text_, 5, 0);
    wifi_button_ = Button(drawer_panel_, "重新配网", 16, 332, 152, 48);
    shutdown_button_ = Button(drawer_panel_, "关机", 184, 332, 152, 48);
    Hidden(drawer_, true);
}
void AirView::CreateConfirmation() {
    confirmation_ = Box(root_, 0, 0, 368, 448);
    lv_obj_add_flag(confirmation_, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_set_style_bg_color(confirmation_, lv_color_black(), 0);
    lv_obj_set_style_bg_opa(confirmation_, LV_OPA_50, 0);
    confirmation_panel_ = Box(confirmation_, 16, 114, 336, 222, 20);
    surfaces_.push_back(confirmation_panel_);
    confirmation_title_ = Label(confirmation_panel_, "确认关机？", 20, 20, 296, &font_air_text_20);
    confirmation_body_ =
        Label(confirmation_panel_, "将停止检测并关闭设备。", 20, 62, 296, &font_air_text_18, true);
    cancel_button_ = Button(confirmation_panel_, "取消", 16, 156, 144, 48);
    confirm_button_ = Button(confirmation_panel_, "确认", 176, 156, 144, 48);
    Hidden(confirmation_, true);
}
void AirView::ApplyTheme() {
    if (!root_)
        return;
    palette_ = state_.night()
                   ? Palette{0x08150F, 0xE8F1E5, 0xADBEAF, 0xB8E684, 0xB8E684, 0x305644, 0x17372B}
                   : Palette{0xEEF5EC, 0x153D32, 0x658475, 0x146B55, 0xC6EF87, 0xD4E4D5, 0xDBEED8};
    last_night_ = state_.night();
    lv_obj_set_style_bg_color(toast_, lv_color_hex(palette_.text), 0);
    lv_obj_set_style_bg_color(root_, lv_color_hex(palette_.bg), 0);
    lv_obj_set_style_bg_color(decoration_, lv_color_hex(palette_.soft), 0);
    lv_obj_set_style_bg_opa(decoration_, LV_OPA_50, 0);
    for (auto* label : primary_)
        lv_obj_set_style_text_color(label, lv_color_hex(palette_.text), 0);
    for (auto* label : secondary_)
        lv_obj_set_style_text_color(label, lv_color_hex(palette_.muted), 0);
    for (auto* label : inverted_)
        lv_obj_set_style_text_color(label, lv_color_hex(0xF1FAEE), 0);
    lv_obj_set_style_text_color(toast_text_, lv_color_hex(palette_.bg), 0);
    for (auto* button : round_buttons_) {
        lv_obj_set_style_bg_color(button, lv_color_hex(palette_.soft), 0);
        lv_obj_set_style_transform_scale(button, state_.reduce_motion ? 256 : 244,
                                         LV_STATE_PRESSED);
    }
    for (auto* surface : surfaces_) {
        lv_obj_set_style_bg_opa(surface, LV_OPA_COVER, 0);
        lv_obj_set_style_bg_color(surface, lv_color_hex(palette_.soft), 0);
    }
    for (auto* rule : rules_) {
        if (!lv_obj_check_type(rule, &lv_line_class)) {
            lv_obj_set_style_bg_opa(rule, LV_OPA_COVER, 0);
            lv_obj_set_style_bg_color(rule, lv_color_hex(palette_.border), 0);
        }
        lv_obj_set_style_line_color(rule, lv_color_hex(palette_.text), 0);
    }
    lv_obj_set_style_bg_color(drawer_panel_, lv_color_hex(palette_.bg), 0);
    lv_obj_set_style_bg_color(confirmation_panel_, lv_color_hex(palette_.bg), 0);
    lv_obj_set_style_bg_color(alert_settings_, lv_color_hex(palette_.bg), 0);
    lv_obj_set_style_bg_color(hcho_card_, lv_color_hex(state_.night() ? 0x145442 : 0x1B8069), 0);
    lv_obj_set_style_bg_grad_color(hcho_card_, lv_color_hex(state_.night() ? 0x0D392B : 0x105E4D),
                                   0);
    lv_obj_set_style_border_color(hcho_card_, lv_color_hex(0x43A48C), 0);
    lv_obj_set_style_bg_color(sample_dot_, lv_color_hex(palette_.accent), 0);
    lv_obj_set_style_line_color(chart_, lv_color_hex(palette_.border), LV_PART_MAIN);
    lv_chart_set_series_color(chart_, series_, lv_color_hex(palette_.accent));
    for (auto* toggle : {motion_switch_, voice_switch_, co2_alert_switch_, hcho_alert_switch_,
                         alert_sound_switch_}) {
        lv_obj_set_style_bg_opa(toggle, LV_OPA_COVER, LV_PART_MAIN);
        lv_obj_set_style_bg_opa(toggle, LV_OPA_COVER, kCheckedIndicator);
        lv_obj_set_style_bg_opa(toggle, LV_OPA_COVER, LV_PART_KNOB);
        for (auto part : {LV_PART_MAIN, LV_PART_INDICATOR, LV_PART_KNOB})
            lv_obj_set_style_radius(toggle, LV_RADIUS_CIRCLE, part);
        lv_obj_set_style_pad_all(toggle, 3, LV_PART_MAIN);
        lv_obj_set_style_bg_color(toggle, lv_color_hex(palette_.border), LV_PART_MAIN);
        lv_obj_set_style_bg_color(toggle, lv_color_hex(palette_.accent), kCheckedIndicator);
        lv_obj_set_style_bg_color(toggle, lv_color_hex(0xFFFFFF), LV_PART_KNOB);
    }
    for (auto* slider : {slider_, volume_slider_, co2_limit_slider_, hcho_limit_slider_}) {
        lv_obj_set_style_bg_color(slider, lv_color_hex(palette_.border), LV_PART_MAIN);
        lv_obj_set_style_bg_color(slider, lv_color_hex(palette_.accent), LV_PART_INDICATOR);
        lv_obj_set_style_bg_color(slider, lv_color_hex(palette_.accent), LV_PART_KNOB);
        lv_obj_set_style_pad_all(slider, 5, LV_PART_KNOB);
        for (auto part : {LV_PART_MAIN, LV_PART_INDICATOR, LV_PART_KNOB}) {
            lv_obj_set_style_radius(slider, LV_RADIUS_CIRCLE, part);
            lv_obj_set_style_bg_opa(slider, LV_OPA_COVER, part);
        }
    }
    RefreshSettings();
    RefreshAlertSettings();
    UpdateFooter();
    TextColor(co2_, ReadingColor(Metric::Co2));
    TextColor(hcho_, ReadingColor(Metric::Hcho, true));
    TextColor(trend_value_, ReadingColor(metric_));
    UpdateHeader();
    last_chart_bucket_ = UINT64_MAX;
}
void AirView::SetBrightness(int percent) {
    state_.SetBrightness(percent);
    RefreshSettings();
    if (callbacks_.brightness)
        callbacks_.brightness(state_.brightness());
    if (callbacks_.preferences)
        callbacks_.preferences();
}
void AirView::SetVolume(int percent) {
    if (!volume_slider_ || volume_dragging_)
        return;
    percent = std::clamp(percent, 0, 100);
    if (lv_slider_get_value(volume_slider_) != percent)
        lv_slider_set_value(volume_slider_, percent, LV_ANIM_OFF);
    UpdateVolumeText();
}
void AirView::UpdateVolumeText() {
    const int percent = lv_slider_get_value(volume_slider_);
    char text[16];
    if (percent == 0)
        std::snprintf(text, sizeof(text), "%s", "静音");
    else
        std::snprintf(text, sizeof(text), "%d%%", percent);
    Text(volume_text_, text);
}
void AirView::RefreshSettings() {
    if (!root_)
        return;
    settings_refresh_ = true;
    lv_slider_set_value(slider_, state_.brightness(), LV_ANIM_OFF);
    char text[16];
    std::snprintf(text, sizeof(text), "%d%%", state_.brightness());
    Text(brightness_text_, text);
    if (state_.reduce_motion)
        lv_obj_add_state(motion_switch_, LV_STATE_CHECKED);
    else
        lv_obj_remove_state(motion_switch_, LV_STATE_CHECKED);
    if (state_.voice_enabled)
        lv_obj_add_state(voice_switch_, LV_STATE_CHECKED);
    else
        lv_obj_remove_state(voice_switch_, LV_STATE_CHECKED);
    for (int i = 0; i < 3; ++i) {
        lv_obj_set_style_bg_color(
            theme_buttons_[i],
            lv_color_hex(i == static_cast<int>(state_.theme_mode()) ? palette_.accent
                                                                    : palette_.soft),
            0);
        lv_obj_set_style_text_color(lv_obj_get_child(theme_buttons_[i], 0),
                                    lv_color_hex(i == static_cast<int>(state_.theme_mode())
                                                     ? (state_.night() ? 0x153D32 : 0xFFFFFF)
                                                     : palette_.text),
                                    0);
    }
    settings_refresh_ = false;
}
void AirView::Refresh(const AirSnapshot& snapshot, const PowerSnapshot& power,
                      DeviceState device_state, bool connected, bool storage_available,
                      const char* connection_info) {
    sample_ = snapshot;
    power_ = power;
    device_state_ = device_state;
    connected_ = connected;
    storage_available_ = storage_available;
    state_.Tick(Now());
    if (!root_)
        return;
    if (state_.night() != last_night_)
        ApplyTheme();
    if (confirmation_id_ && Now() >= confirmation_until_) {
        action_gate_.Cancel(confirmation_id_);
        confirmation_id_ = 0;
        Hidden(confirmation_, true);
    }
    const bool was_chat_visible = ChatVisible();
    if (chat_view_->Update(device_state_, connected_, state_.voice_enabled, state_.night(),
                           state_.reduce_motion,
                           state_.display_on() && !state_.drawer() && !confirmation_id_ &&
                               !alert_settings_open_ && !power_.shutting_down,
                           Now(), callbacks_.wall_time ? callbacks_.wall_time() : 0))
        Navigate(Page::Home, false);
    if (!was_chat_visible && ChatVisible()) {
        lv_anim_delete(this, nullptr);
        dragging_ = touch_eligible_ = false;
        NormalizePages();
    }
    Hidden(drawer_, !state_.drawer());
    Text(toast_text_, state_.notice());
    Hidden(toast_, !state_.notice()[0]);
    if (state_.notice()[0] && !alert_settings_open_ && !confirmation_id_)
        lv_obj_move_foreground(toast_);
    if (state_.page() == Page::Home && !ChatVisible())
        UpdateHome();
    else if (state_.page() == Page::Trend && !ChatVisible())
        UpdateTrend();
    UpdateHeader();
    UpdateFooter();
    if (state_.drawer())
        UpdateDrawer(connection_info);
}
void AirView::UpdateHome() {
    char text[128], age[64];
    const auto& co2 = sample_.co2;
    const auto& hcho = sample_.hcho;
    const bool co2_value = HasDisplayValue(sample_, Metric::Co2);
    const bool hcho_value = HasDisplayValue(sample_, Metric::Hcho);
    if (co2_value)
        std::snprintf(text, sizeof(text), "%u", sample_.scd.ppm);
    else
        std::snprintf(text, sizeof(text), "%s", "—");
    const auto* font =
        co2_value && sample_.scd.ppm >= 10000 ? &font_air_digits_88 : &font_air_digits_120;
    if (lv_obj_get_style_text_font(co2_, LV_PART_MAIN) != font)
        lv_obj_set_style_text_font(co2_, font, 0);
    lv_obj_set_y(co2_, co2_value && sample_.scd.ppm >= 10000 ? 155 : 132);
    Text(co2_, text);
    TextColor(co2_, ReadingColor(Metric::Co2));
    Age(age, sizeof(age), co2, sample_.now_ms);
    if (!co2.ready || !co2.connected || co2.stale || !co2.within_spec || co2.errors >= 3)
        std::snprintf(text, sizeof(text), "%s", Status(co2, false));
    else
        std::snprintf(text, sizeof(text), "%s", age);
    Text(co2_age_, text);
    if (hcho_value)
        std::snprintf(text, sizeof(text), "%ld", std::lround(sample_.sfa.ppb));
    else
        std::snprintf(text, sizeof(text), "%s", "—");
    Text(hcho_, text);
    TextColor(hcho_, ReadingColor(Metric::Hcho, true));
    const auto* hcho_status = Status(hcho, true);
    Text(hcho_status_, std::strcmp(hcho_status, "已就绪") == 0 ? "HCHO" : hcho_status);
    const bool partial_error = co2.stale || hcho.stale || co2.errors >= 3 || hcho.errors >= 3 ||
                               !co2.environment_ok || !hcho.environment_ok ||
                               (co2.ready && !co2.within_spec);
    Text(status_, power_.shutting_down                  ? "正在关机"
                  : partial_error                       ? "部分异常"
                  : !co2.has_value || !hcho.within_spec ? "部分预热"
                                                        : "实时监测");
    Background(status_pill_,
               alerts_.active ? (state_.night() ? 0x664321 : 0xF3D4B5) : palette_.soft);
    if (alerts_.active && !power_.shutting_down) {
        Text(status_, alerts_.unavailable ? "此前偏高" : "浓度偏高");
        if (alerts_.active & kAlertCo2) {
            Text(co2_age_,
                 alerts_.unavailable & kAlertCo2 ? "此前偏高，数据暂不可用" : "仍高于提醒值");
        }
        if (alerts_.active & kAlertHcho)
            Text(hcho_status_, alerts_.unavailable & kAlertHcho ? "此前偏高" : "仍高于提醒值");
    }
    if (co2_value)
        std::snprintf(text, sizeof(text), "%.1f°C", sample_.scd.temperature);
    else
        std::snprintf(text, sizeof(text), "%s", "—");
    Text(temperature_, text);
    if (co2_value)
        std::snprintf(text, sizeof(text), "%ld%%", std::lround(sample_.scd.humidity));
    else
        std::snprintf(text, sizeof(text), "%s", "—");
    Text(humidity_, text);
    for (auto* label : {temperature_, humidity_})
        TextColor(label, co2.stale ? palette_.muted : palette_.text);
    if (co2_value && co2.last_value_ms != last_sample_ms_) {
        last_sample_ms_ = co2.last_value_ms;
        if (!state_.reduce_motion) {
            lv_anim_delete(sample_dot_, nullptr);
            lv_anim_t pulse;
            lv_anim_init(&pulse);
            lv_anim_set_var(&pulse, sample_dot_);
            lv_anim_set_values(&pulse, 255, 110);
            lv_anim_set_delay(&pulse, 80);
            lv_anim_set_duration(&pulse, 180);
            lv_anim_set_exec_cb(&pulse, [](void* obj, int32_t value) {
                lv_obj_set_style_bg_opa(static_cast<lv_obj_t*>(obj), value, 0);
            });
            lv_anim_start(&pulse);
        }
    }
}
void AirView::UpdateTrend() {
    char text[96];
    const auto& channel = metric_ == Metric::Co2 ? sample_.co2 : sample_.hcho;
    if (HasDisplayValue(sample_, metric_)) {
        std::snprintf(text, sizeof(text), "%ld",
                      std::lround(metric_ == Metric::Co2 ? sample_.scd.ppm : sample_.sfa.ppb));
    } else
        std::snprintf(text, sizeof(text), "%s", "—");
    Text(trend_value_, text);
    TextColor(trend_value_, ReadingColor(metric_));
    Text(trend_unit_, metric_ == Metric::Co2 ? "ppm" : "ppb");
    Age(text, sizeof(text), channel, sample_.now_ms);
    Text(trend_age_, channel.stale || !channel.ready || !channel.connected || !channel.within_spec
                         ? Status(channel, metric_ == Metric::Hcho)
                         : text);
    for (int i = 0; i < 2; ++i) {
        const bool selected = (i == 0) == (metric_ == Metric::Co2);
        Background(selector_[i], selected ? palette_.accent : palette_.soft);
        TextColor(lv_obj_get_child(selector_[i], 0),
                  selected ? (state_.night() ? 0x153D32 : 0xFFFFFF) : palette_.text);
    }
    const uint64_t bucket = sample_.now_ms / 5000;
    if (bucket == last_chart_bucket_)
        return;
    last_chart_bucket_ = bucket;
    if (callbacks_.history)
        callbacks_.history(metric_, history_);
    int32_t maximum = metric_ == Metric::Co2 ? 1000 : 50;
    bool any = false;
    for (size_t i = 0; i < kHistorySize; ++i) {
        int32_t value = LV_CHART_POINT_NONE;
        if (bucket + i >= kHistorySize - 1) {
            const uint64_t wanted = bucket + i - (kHistorySize - 1);
            const auto& point = history_[wanted % kHistorySize];
            if (point.valid && point.bucket == wanted) {
                value = std::lround(point.value);
                maximum = std::max(maximum, value);
                any = true;
            }
        }
        lv_chart_set_series_value_by_id2(chart_, series_, i, i, value);
    }
    const int step = metric_ == Metric::Co2 ? 500 : 50;
    maximum = ((maximum + step - 1) / step) * step;
    lv_chart_set_axis_range(chart_, LV_CHART_AXIS_PRIMARY_Y, 0, maximum);
    std::snprintf(text, sizeof(text), "%ld", static_cast<long>(maximum));
    Text(axis_max_, text);
    Hidden(chart_empty_, any);
    lv_chart_refresh(chart_);
}
void AirView::UpdateFooter() {
    const char* status = !state_.voice_enabled                          ? "语音已关"
                         : !connected_                                  ? "语音离线"
                         : device_state_ == kDeviceStateListening       ? "正在聆听"
                         : device_state_ == kDeviceStateSpeaking        ? "正在回复"
                         : device_state_ == kDeviceStateActivating      ? "等待激活"
                         : device_state_ == kDeviceStateWifiConfiguring ? "配网中"
                                                                        : "语音";
    Text(mic_text_, status);
    Text(lv_obj_get_child(mic_, 0),
         state_.voice_enabled ? MATERIAL_SYMBOLS_MIC : MATERIAL_SYMBOLS_MIC_OFF);
    Text(shortcut_icon_,
         state_.page() == Page::Home ? MATERIAL_SYMBOLS_SETTINGS : MATERIAL_SYMBOLS_HOME);
    for (int i = 0; i < 3; ++i)
        Background(dots_[i],
                   static_cast<int>(state_.page()) == i ? palette_.accent : palette_.border);
    const bool listening = state_.voice_enabled && connected_ &&
                           device_state_ == kDeviceStateListening && !state_.reduce_motion &&
                           state_.display_on() && !ChatVisible();
    if (listening != listening_) {
        listening_ = listening;
        lv_anim_delete(mic_, nullptr);
        lv_obj_set_style_opa(mic_, LV_OPA_COVER, 0);
        if (listening) {
            lv_anim_t pulse;
            lv_anim_init(&pulse);
            lv_anim_set_var(&pulse, mic_);
            lv_anim_set_values(&pulse, 180, 255);
            lv_anim_set_duration(&pulse, 550);
            lv_anim_set_playback_duration(&pulse, 550);
            lv_anim_set_repeat_count(&pulse, LV_ANIM_REPEAT_INFINITE);
            lv_anim_set_exec_cb(&pulse, [](void* obj, int32_t value) {
                lv_obj_set_style_opa(static_cast<lv_obj_t*>(obj), value, 0);
            });
            lv_anim_start(&pulse);
        }
    }
}
void AirView::UpdateDrawer(const char* connection_info) {
    char text[896], co2_age[64], hcho_age[64];
    Age(co2_age, sizeof(co2_age), sample_.co2, sample_.now_ms);
    Age(hcho_age, sizeof(hcho_age), sample_.hcho, sample_.now_ms);
    std::snprintf(
        text, sizeof(text),
        "SCD41 · %s\nCO₂：%s\nSFA40 · %s\n甲醛：%s\n温湿度来源：SCD41\n自动校准 ASC：%s\n%s\n%s",
        Status(sample_.co2, false), co2_age, Status(sample_.hcho, true), hcho_age,
        sample_.asc_enabled < 0 ? "未知"
        : sample_.asc_enabled   ? "开启"
                                : "关闭",
        connection_info ? connection_info
        : connected_    ? "Wi-Fi 已连接"
                        : "Wi-Fi 离线",
        storage_available_ ? "设置可保存" : "存储不可用，设置暂存");
    Text(drawer_text_, text);
    Text(lv_obj_get_child(wifi_button_, 0),
         device_state_ == kDeviceStateWifiConfiguring ? "退出配网" : "重新配网");
}
void AirView::RequestAction(DeviceAction action) {
    if (!root_ || power_.shutting_down)
        return;
    const auto pending = action_gate_.Request(action, Now());
    confirmation_id_ = pending.id;
    confirmation_until_ = pending.expires_ms;
    Text(confirmation_title_,
         action == DeviceAction::ConfigureWifi ? "确认重新配网？" : "确认关机？");
    Text(confirmation_body_, action == DeviceAction::ConfigureWifi
                                 ? "进入配网后，空气检测继续运行。"
                                 : "将停止检测并关闭设备。");
    Hidden(confirmation_, false);
    lv_obj_move_foreground(confirmation_);
    lv_indev_reset(nullptr, nullptr);
}
void AirView::Event(lv_event_t* event) {
    static_cast<AirView*>(lv_event_get_user_data(event))->Handle(event);
}
void AirView::FilterSliderTouch(lv_event_t* event) {
    auto* input = lv_indev_active();
    if (!input || lv_indev_get_type(input) != LV_INDEV_TYPE_POINTER)
        return;
    auto* self = static_cast<AirView*>(lv_event_get_user_data(event));
    lv_point_t point;
    lv_indev_get_point(input, &point);
    if (lv_event_get_code(event) == LV_EVENT_PRESSED)
        self->slider_touch_start_ = point;
    else if (lv_event_get_code(event) == LV_EVENT_PRESSING &&
             !lv_slider_is_dragged(lv_event_get_target_obj(event)) &&
             std::abs(point.y - self->slider_touch_start_.y) >
                 std::abs(point.x - self->slider_touch_start_.x)) {
        // Let the list claim vertical motion before the slider changes its value
        // and disables vertical scroll chaining. Keep an established horizontal drag.
        lv_event_stop_processing(event);
    }
}
void AirView::Handle(lv_event_t* event) {
    auto* target = lv_event_get_target_obj(event);
    const auto code = lv_event_get_code(event);
    if (power_.shutting_down || settings_refresh_ || (ChatVisible() && !confirmation_id_))
        return;
    if (target == co2_limit_slider_ || target == hcho_limit_slider_) {
        if (code == LV_EVENT_VALUE_CHANGED) {
            const int raw = lv_slider_get_value(target);
            if (target == co2_limit_slider_)
                state_.alerts.co2_ppm = ((raw + 50) / 100) * 100;
            else
                state_.alerts.hcho_ppb = ((raw + 2) / 5) * 5;
            RefreshAlertSettings();
            if (callbacks_.alerts_changed)
                callbacks_.alerts_changed();
        } else if ((code == LV_EVENT_RELEASED || code == LV_EVENT_PRESS_LOST) &&
                   callbacks_.preferences)
            callbacks_.preferences();
        return;
    }
    if ((target == co2_alert_switch_ || target == hcho_alert_switch_ ||
         target == alert_sound_switch_) &&
        code == LV_EVENT_VALUE_CHANGED) {
        const bool enabled = lv_obj_has_state(target, LV_STATE_CHECKED);
        if (target == co2_alert_switch_)
            state_.alerts.co2_enabled = enabled;
        else if (target == hcho_alert_switch_)
            state_.alerts.hcho_enabled = enabled;
        else
            state_.alerts.sound = enabled;
        if (callbacks_.preferences)
            callbacks_.preferences();
        if (callbacks_.alerts_changed)
            callbacks_.alerts_changed();
        return;
    }
    if (target == volume_slider_) {
        if (code == LV_EVENT_PRESSED)
            volume_dragging_ = true;
        else if (code == LV_EVENT_VALUE_CHANGED) {
            volume_changed_ = true;
            // Keep dragging local; codec I2C and NVS work waits for release.
            UpdateVolumeText();
        } else if (code == LV_EVENT_RELEASED || code == LV_EVENT_PRESS_LOST) {
            volume_dragging_ = false;
            if (volume_changed_ && callbacks_.volume)
                callbacks_.volume(lv_slider_get_value(volume_slider_));
            volume_changed_ = false;
        }
        return;
    }
    if (target == slider_) {
        if (code == LV_EVENT_VALUE_CHANGED) {
            state_.SetBrightness(lv_slider_get_value(slider_));
            char text[16];
            std::snprintf(text, sizeof(text), "%d%%", state_.brightness());
            Text(brightness_text_, text);
            if (callbacks_.brightness)
                callbacks_.brightness(state_.brightness());
        } else if (code == LV_EVENT_RELEASED && callbacks_.preferences)
            callbacks_.preferences();
        return;
    }
    if ((target == motion_switch_ || target == voice_switch_) && code == LV_EVENT_VALUE_CHANGED) {
        const bool enabled = lv_obj_has_state(target, LV_STATE_CHECKED);
        if (target == motion_switch_) {
            state_.reduce_motion = enabled;
            StopAnimation();
            ApplyTheme();
        } else {
            state_.voice_enabled = enabled;
            if (callbacks_.voice_enabled)
                callbacks_.voice_enabled(enabled);
        }
        if (callbacks_.preferences)
            callbacks_.preferences();
        UpdateFooter();
        return;
    }
    if (code != LV_EVENT_CLICKED)
        return;
    if (target == mic_) {
        const bool start = device_state_ == kDeviceStateIdle && connected_ &&
                           state_.voice_enabled && callbacks_.voice;
        ShowChat(start);
        if (start)
            callbacks_.voice();
    } else if (target == shortcut_)
        Navigate(state_.page() == Page::Home ? Page::Settings : Page::Home);
    else if (target == back_[0] || target == back_[1])
        Navigate(Page::Home);
    else if (target == selector_[0] || target == selector_[1]) {
        metric_ = target == selector_[0] ? Metric::Co2 : Metric::Hcho;
        last_chart_bucket_ = UINT64_MAX;
        UpdateTrend();
    } else if (target == theme_buttons_[0] || target == theme_buttons_[1] ||
               target == theme_buttons_[2]) {
        state_.SetThemeMode(target == theme_buttons_[2]   ? ThemeMode::Auto
                            : target == theme_buttons_[1] ? ThemeMode::Night
                                                          : ThemeMode::Day);
        ApplyTheme();
        if (callbacks_.brightness)
            callbacks_.brightness(state_.brightness());
        if (callbacks_.preferences)
            callbacks_.preferences();
    } else if (target == alert_button_) {
        alert_settings_open_ = true;
        RefreshAlertSettings();
        Hidden(alert_settings_, false);
        lv_obj_move_foreground(alert_settings_);
    } else if (target == alert_settings_back_) {
        alert_settings_open_ = false;
        Hidden(alert_settings_, true);
    } else if (target == detail_button_) {
        state_.SetDrawer(true);
        Hidden(drawer_, false);
    } else if (target == drawer_close_) {
        state_.SetDrawer(false);
        Hidden(drawer_, true);
    } else if (target == wifi_button_) {
        if (device_state_ == kDeviceStateWifiConfiguring) {
            if (callbacks_.cancel_config)
                callbacks_.cancel_config();
        } else
            RequestAction(DeviceAction::ConfigureWifi);
    } else if (target == shutdown_button_)
        RequestAction(DeviceAction::Shutdown);
    else if (target == cancel_button_) {
        action_gate_.Cancel(confirmation_id_);
        confirmation_id_ = 0;
        Hidden(confirmation_, true);
    } else if (target == confirm_button_) {
        const auto action = action_gate_.Confirm(confirmation_id_, Now());
        confirmation_id_ = 0;
        Hidden(confirmation_, true);
        if (action && callbacks_.confirmed_action)
            callbacks_.confirmed_action(*action);
    }
}
void AirView::NormalizePages() {
    if (!root_)
        return;
    for (int i = 0; i < 3; ++i) {
        lv_obj_set_x(pages_[i], 0);
        Hidden(pages_[i], i != static_cast<int>(state_.page()));
    }
}
void AirView::StopAnimation() {
    if (chat_view_)
        chat_view_->Suspend(Now());
    lv_anim_delete(this, nullptr);
    if (mic_)
        lv_anim_delete(mic_, nullptr);
    if (sample_dot_)
        lv_anim_delete(sample_dot_, nullptr);
    listening_ = false;
    dragging_ = false;
    touch_eligible_ = false;
    NormalizePages();
}
void AirView::SetTransition(int32_t progress) {
    lv_obj_set_x(pages_[transition_from_], -transition_dir_ * progress);
    lv_obj_set_x(pages_[transition_to_], transition_dir_ * (kWidth - progress));
}
void AirView::WakeHome() {
    if (chat_view_)
        chat_view_->Close();
    action_gate_.Cancel(confirmation_id_);
    confirmation_id_ = 0;
    state_.SetPage(Page::Home);
    alert_settings_open_ = false;
    if (!root_)
        return;
    Hidden(confirmation_, true);
    Hidden(drawer_, true);
    Hidden(alert_settings_, true);
    StopAnimation();
    UpdateHome();
    UpdateFooter();
}
void AirView::Navigate(Page page, bool animate) {
    if (chat_view_)
        chat_view_->Close();
    if (!root_) {
        state_.SetPage(page);
        return;
    }
    const int from = static_cast<int>(state_.page()), to = static_cast<int>(page);
    if (from == to) {
        StopAnimation();
        return;
    }
    const int start =
        dragging_ && transition_from_ == from && transition_to_ == to ? drag_progress_ : 0;
    dragging_ = false;
    touch_eligible_ = false;
    lv_anim_delete(this, nullptr);
    NormalizePages();
    transition_from_ = from;
    transition_to_ = to;
    transition_dir_ = to > from ? 1 : -1;
    state_.SetPage(page);
    if (page == Page::Trend)
        UpdateTrend();
    if (page == Page::Home)
        UpdateHome();
    UpdateFooter();
    if (!animate || state_.reduce_motion) {
        NormalizePages();
        return;
    }
    Hidden(pages_[to], false);
    AnimateTransition(start, kWidth);
}
void AirView::AnimateTransition(int from, int to) {
    SetTransition(from);
    lv_anim_t animation;
    lv_anim_init(&animation);
    lv_anim_set_var(&animation, this);
    lv_anim_set_values(&animation, from, to);
    lv_anim_set_duration(&animation, std::max(80, 200 * std::abs(to - from) / kWidth));
    lv_anim_set_path_cb(&animation, lv_anim_path_ease_out);
    lv_anim_set_exec_cb(&animation, [](void* ctx, int32_t value) {
        static_cast<AirView*>(ctx)->SetTransition(value);
    });
    lv_anim_set_completed_cb(&animation,
                             [](lv_anim_t* a) { static_cast<AirView*>(a->var)->NormalizePages(); });
    lv_anim_start(&animation);
}
void AirView::Touch(lv_event_t* event) {
    static_cast<AirView*>(lv_event_get_user_data(event))->HandleTouch(event);
}
void AirView::HandleTouch(lv_event_t* event) {
    if (state_.drawer() || confirmation_id_ || power_.shutting_down || alert_settings_open_ ||
        ChatVisible())
        return;
    auto* input = lv_indev_active();
    if (!input)
        return;
    lv_point_t point;
    lv_indev_get_point(input, &point);
    const auto code = lv_event_get_code(event);
    if (code == LV_EVENT_PRESSED) {
        StopAnimation();
        touch_start_ = point;
        touch_eligible_ = state_.page() != Page::Settings || point.x < 20 || point.x >= 348;
        drag_progress_ = 0;
    } else if (code == LV_EVENT_PRESSING && touch_eligible_) {
        const int dx = point.x - touch_start_.x, dy = point.y - touch_start_.y;
        if (!dragging_ && std::abs(dy) > 16 && std::abs(dy) > std::abs(dx)) {
            touch_eligible_ = false;
            return;
        }
        const int target = static_cast<int>(state_.page()) + (dx < 0 ? 1 : -1);
        if (!dragging_ && (target < 0 || target > 2))
            return;
        if (!dragging_ && std::abs(dx) >= 24 && std::abs(dx) > std::abs(dy) * 2) {
            dragging_ = true;
            transition_from_ = static_cast<int>(state_.page());
            transition_to_ = target;
            transition_dir_ = dx < 0 ? 1 : -1;
            // Prepare the incoming page before exposing it, and reuse it on release.
            if (target == static_cast<int>(Page::Trend))
                UpdateTrend();
            else if (target == static_cast<int>(Page::Home))
                UpdateHome();
            Hidden(pages_[target], false);
        }
        if (dragging_) {
            drag_progress_ = std::clamp(transition_dir_ * -dx, 0, kWidth);
            if (!state_.reduce_motion)
                SetTransition(drag_progress_);
        }
    } else if ((code == LV_EVENT_RELEASED || code == LV_EVENT_PRESS_LOST) && dragging_) {
        const auto destination = static_cast<Page>(transition_to_);
        const bool commit = code == LV_EVENT_RELEASED && drag_progress_ >= 64;
        if (commit) {
            Navigate(destination);
        } else {
            dragging_ = false;
            touch_eligible_ = false;
            if (state_.reduce_motion)
                NormalizePages();
            else
                AnimateTransition(drag_progress_, 0);
        }
    }
}
}  // namespace air
