#include "air_chat_view.h"
#include <material_symbols.h>
#include <algorithm>
#include <cmath>
#include <cstring>
#include <string>
#include <string_view>
#include "air_clock.h"
#include "air_fonts.h"

LV_FONT_DECLARE(font_material_symbols_20_4);
LV_FONT_DECLARE(font_material_symbols_30_4);
namespace air {
namespace {
bool Active(DeviceState state) {
    return state == kDeviceStateConnecting || state == kDeviceStateListening ||
           state == kDeviceStateSpeaking;
}
std::string DisplayText(std::string_view text) {
    std::string result;
    result.reserve(text.size());
    for (size_t i = 0; i < text.size();) {
        const auto lead = static_cast<unsigned char>(text[i]);
        const size_t count = lead < 0x80 ? 1 : lead < 0xE0 ? 2 : lead < 0xF0 ? 3 : 4;
        uint32_t code = lead & (count == 1 ? 0x7F : 0x7F >> count);
        for (size_t j = 1; j < count; ++j)
            code = (code << 6) | (static_cast<unsigned char>(text[i + j]) & 0x3F);
        lv_font_glyph_dsc_t glyph{};
        if (code == '\n' ||
            (lv_font_get_glyph_dsc(&font_air_chat_18, &glyph, code, 0) && !glyph.is_placeholder))
            result.append(text.substr(i, count));
        else
            result += "\xEF\xBF\xBD";
        i += count;
    }
    return result;
}
void Hidden(lv_obj_t* object, bool hide) {
    if (hide)
        lv_obj_add_flag(object, LV_OBJ_FLAG_HIDDEN);
    else
        lv_obj_remove_flag(object, LV_OBJ_FLAG_HIDDEN);
}
void Text(lv_obj_t* label, const char* value) {
    if (std::strcmp(lv_label_get_text(label), value) != 0)
        lv_label_set_text(label, value);
}
void Color(lv_obj_t* object, uint32_t color) {
    if (!lv_color_eq(lv_obj_get_style_text_color(object, LV_PART_MAIN), lv_color_hex(color)))
        lv_obj_set_style_text_color(object, lv_color_hex(color), 0);
}
void Background(lv_obj_t* object, uint32_t color) {
    if (!lv_color_eq(lv_obj_get_style_bg_color(object, LV_PART_MAIN), lv_color_hex(color)))
        lv_obj_set_style_bg_color(object, lv_color_hex(color), 0);
}
lv_obj_t* Box(lv_obj_t* parent, int x, int y, int width, int height, int radius = 0) {
    auto* object = lv_obj_create(parent);
    lv_obj_remove_style_all(object);
    lv_obj_set_pos(object, x, y);
    lv_obj_set_size(object, width, height);
    lv_obj_set_style_radius(object, radius, 0);
    lv_obj_remove_flag(object, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_remove_flag(object, LV_OBJ_FLAG_CLICKABLE);
    return object;
}
lv_obj_t* Label(lv_obj_t* parent, const char* text, int x, int y, int width,
                const lv_font_t* font = &font_air_text_18) {
    auto* label = lv_label_create(parent);
    lv_obj_remove_style_all(label);
    lv_obj_set_pos(label, x, y);
    lv_obj_set_width(label, width);
    lv_obj_set_style_text_font(label, font, 0);
    lv_label_set_long_mode(label, LV_LABEL_LONG_WRAP);
    lv_label_set_text(label, text);
    return label;
}
}  // namespace
AirChatView::~AirChatView() {
    StopAnimation();
    if (root_)
        lv_obj_delete(root_);
}
void AirChatView::Create(lv_obj_t* parent) {
    root_ = Box(parent, 0, 0, 368, 448);
    lv_obj_set_style_bg_opa(root_, LV_OPA_COVER, 0);
    lv_obj_add_flag(root_, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_add_event_cb(root_, Event, LV_EVENT_ALL, this);
    decoration_ = Box(root_, 282, -116, 252, 252, 126);
    lv_obj_set_style_bg_opa(decoration_, LV_OPA_50, 0);
    back_ = Box(root_, 8, 12, 48, 48);
    lv_obj_add_flag(back_, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_add_flag(back_, LV_OBJ_FLAG_EVENT_BUBBLE);
    lv_obj_add_event_cb(back_, Event, LV_EVENT_ALL, this);
    auto* back_icon =
        Label(back_, MATERIAL_SYMBOLS_ARROW_BACK, 9, 9, 30, &font_material_symbols_30_4);
    title_ = Label(root_, "小智对话", 66, 24, 132, &font_air_text_20);
    clock_ = Label(root_, "--:--", 246, 25, 62);
    lv_label_set_long_mode(clock_, LV_LABEL_LONG_CLIP);
    wifi_ = Label(root_, MATERIAL_SYMBOLS_WIFI_OFF, 322, 24, 22, &font_material_symbols_20_4);
    rule_ = Box(root_, 24, 64, 320, 1);
    meta_ = Label(root_, "本次对话", 24, 80, 164);
    online_ = Label(root_, "离线", 284, 80, 60);
    lv_obj_set_style_text_align(online_, LV_TEXT_ALIGN_RIGHT, 0);
    body_ = Box(root_, 16, 112, 336, 260);
    lv_obj_add_flag(body_, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_add_flag(body_, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_add_flag(body_, LV_OBJ_FLAG_EVENT_BUBBLE);
    lv_obj_set_scroll_dir(body_, LV_DIR_VER);
    lv_obj_set_scrollbar_mode(body_, LV_SCROLLBAR_MODE_AUTO);
    lv_obj_remove_flag(body_, LV_OBJ_FLAG_GESTURE_BUBBLE);
    lv_obj_add_event_cb(body_, Event, LV_EVENT_ALL, this);
    empty_ = Box(root_, 16, 112, 336, 260);
    empty_disk_ = Box(empty_, 116, 30, 104, 104, 52);
    lv_obj_set_style_bg_opa(empty_disk_, LV_OPA_40, 0);
    empty_inner_ = Box(empty_disk_, 14, 14, 76, 76, 38);
    lv_obj_set_style_bg_opa(empty_inner_, LV_OPA_COVER, 0);
    empty_mic_ = Label(empty_inner_, MATERIAL_SYMBOLS_MIC, 23, 23, 30, &font_material_symbols_30_4);
    empty_title_ = Label(empty_, "你说，我在听", 16, 144, 304, &font_air_text_20);
    empty_hint_ = Label(empty_, "试着问问车内空气", 16, 184, 304);
    for (auto* label : {empty_title_, empty_hint_})
        lv_obj_set_style_text_align(label, LV_TEXT_ALIGN_CENTER, 0);
    latest_ = Box(root_, 216, 76, 136, 32, 16);
    lv_obj_set_style_bg_opa(latest_, LV_OPA_COVER, 0);
    lv_obj_add_flag(latest_, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_add_event_cb(latest_, Event, LV_EVENT_ALL, this);
    latest_text_ = Label(latest_, "回到最新", 8, 5, 120);
    lv_obj_set_style_text_align(latest_text_, LV_TEXT_ALIGN_CENTER, 0);
    footer_rule_ = Box(root_, 16, 376, 336, 1);
    status_pill_ = Box(root_, 16, 388, 216, 48, 24);
    lv_obj_set_style_bg_opa(status_pill_, LV_OPA_COVER, 0);
    for (int i = 0; i < 5; ++i) {
        bars_[i] = Box(status_pill_, 17 + i * 6, 14, 3, 20, 2);
        lv_obj_set_style_bg_opa(bars_[i], LV_OPA_COVER, 0);
    }
    status_ = Label(status_pill_, "对话结束", 61, 13, 144);
    action_ = Box(root_, 244, 388, 108, 48, 24);
    lv_obj_set_style_bg_opa(action_, LV_OPA_COVER, 0);
    lv_obj_add_flag(action_, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_add_event_cb(action_, Event, LV_EVENT_ALL, this);
    action_icon_ = Label(action_, MATERIAL_SYMBOLS_STOP, 13, 14, 20, &font_material_symbols_20_4);
    action_text_ = Label(action_, "开始说话", 0, 13, 108);
    ApplyTheme();
    Color(back_icon, 0x153D32);
    Hidden(root_, true);
}
void AirChatView::Open(uint64_t now_ms, bool voice_intent) {
    edge_candidate_ = false;
    ignore_back_click_ = true;
    pending_start_ = voice_intent && !model_.active();
    suppress_pending_start_ = false;
    model_.Open(now_ms);
    follow_latest_ = true;
    if (root_) {
        Hidden(root_, false);
        RenderTranscript();
        FollowLatest();
    }
}
void AirChatView::Close() {
    edge_candidate_ = false;
    ignore_back_click_ = true;
    if (pending_start_ && !model_.active())
        suppress_pending_start_ = true;
    model_.Close();
    StopAnimation();
    if (root_)
        Hidden(root_, true);
}
void AirChatView::Append(const char* role, const char* text) {
    const auto revision = model_.revision();
    model_.Append(role ? role : "", text ? text : "");
    if (model_.revision() != revision && role) {
        if (std::strcmp(role, "user") == 0)
            awaiting_reply_ = true;
        else if (std::strcmp(role, "assistant") == 0)
            awaiting_reply_ = false;
    }
}
void AirChatView::Remove(const char* role, const char* text) {
    model_.Remove(role ? role : "", text ? text : "");
}
bool AirChatView::Update(DeviceState state, bool connected, bool enabled, bool night,
                         bool reduce_motion, bool foreground, uint64_t now_ms,
                         std::time_t wall_time) {
    foreground_ = foreground;
    if (!foreground) {
        edge_candidate_ = false;
        ignore_back_click_ = true;
    }
    const bool active = enabled && Active(state);
    const bool new_session = active && !model_.active();
    model_.SetActive(active, now_ms);
    if (new_session) {
        follow_latest_ = true;
        pending_start_ = false;
        if (suppress_pending_start_) {
            model_.Close();
            suppress_pending_start_ = false;
        }
    }
    const bool returned = model_.Tick(now_ms, foreground);
    state_ = state;
    connected_ = connected;
    enabled_ = enabled;
    if (!active) {
        stop_pending_ = false;
        awaiting_reply_ = false;
    }
    if (night != night_ || !themed_) {
        night_ = night;
        ApplyTheme();
    }
    Hidden(root_, !model_.visible());
    if (!model_.visible()) {
        StopAnimation();
        return returned;
    }
    RenderTranscript();
    if (new_session)
        FollowLatest();
    const auto time = FormatLocalClock(wall_time);
    Text(clock_, std::strlen(time.data()) == 11 ? time.data() + 6 : time.data());
    Text(wifi_, connected ? MATERIAL_SYMBOLS_WIFI : MATERIAL_SYMBOLS_WIFI_OFF);
    Color(wifi_, connected ? (night ? 0xE8F1E5 : 0x153D32) : (night ? 0xADBEAF : 0x658475));
    Text(online_, connected ? "在线" : "离线");
    const char* status = !enabled                          ? "语音已关闭"
                         : stop_pending_                   ? "正在停止"
                         : !connected                      ? "语音离线"
                         : state == kDeviceStateConnecting ? "正在连接"
                         : state == kDeviceStateSpeaking   ? "正在回复"
                         : state == kDeviceStateListening
                             ? (awaiting_reply_ ? "正在思考" : "正在聆听")
                             : "对话结束";
    Text(status_, status);
    Hidden(action_icon_, !active);
    lv_obj_set_x(action_text_, active ? 41 : 0);
    lv_obj_set_width(action_text_, active ? 64 : 108);
    const auto align = active ? LV_TEXT_ALIGN_LEFT : LV_TEXT_ALIGN_CENTER;
    if (lv_obj_get_style_text_align(action_text_, LV_PART_MAIN) != align)
        lv_obj_set_style_text_align(action_text_, align, 0);
    Text(action_text_, active ? "停止" : "开始说话");
    if (stop_pending_ || (!active && (!enabled || !connected)))
        lv_obj_add_state(action_, LV_STATE_DISABLED);
    else
        lv_obj_remove_state(action_, LV_STATE_DISABLED);
    const auto opacity = lv_obj_has_state(action_, LV_STATE_DISABLED) ? LV_OPA_50 : LV_OPA_COVER;
    if (lv_obj_get_style_opa(action_, LV_PART_MAIN) != opacity)
        lv_obj_set_style_opa(action_, opacity, 0);
    Text(empty_title_, active && state != kDeviceStateSpeaking ? "你说，我在听" : "暂无对话记录");
    Text(empty_hint_, !enabled ? "语音已关闭" : !connected ? "请先连接Wi-Fi" : "试着问问车内空气");
    Hidden(latest_, follow_latest_ || model_.messages().empty());
    Hidden(online_, !follow_latest_ && !model_.messages().empty());
    const bool animate = active && foreground && !reduce_motion && !stop_pending_;
    if (!animate)
        StopAnimation();
    else if (!animating_) {
        animating_ = true;
        lv_anim_t animation;
        lv_anim_init(&animation);
        lv_anim_set_var(&animation, this);
        lv_anim_set_values(&animation, 0, 100);
        lv_anim_set_duration(&animation, 1040);
        lv_anim_set_repeat_count(&animation, LV_ANIM_REPEAT_INFINITE);
        lv_anim_set_exec_cb(&animation, [](void* context, int32_t phase) {
            auto* self = static_cast<AirChatView*>(context);
            for (int i = 0; i < 5; ++i) {
                const int height = 8 + static_cast<int>(std::lround(
                                           (1 + std::sin((phase + i * 17) * 0.062831853f)) * 11));
                lv_obj_set_height(self->bars_[i], height);
                lv_obj_set_y(self->bars_[i], (48 - height) / 2);
            }
        });
        lv_anim_start(&animation);
    }
    return returned;
}
void AirChatView::StopAnimation() {
    if (!animating_)
        return;
    lv_anim_delete(this, nullptr);
    animating_ = false;
    for (int i = 0; i < 5; ++i) {
        lv_obj_set_height(bars_[i], 8 + i % 3 * 5);
        lv_obj_set_y(bars_[i], (48 - lv_obj_get_height(bars_[i])) / 2);
    }
}
void AirChatView::FollowLatest() {
    lv_obj_update_layout(body_);
    const int bottom =
        std::max<int32_t>(0, lv_obj_get_scroll_y(body_) + lv_obj_get_scroll_bottom(body_));
    lv_obj_scroll_to_y(body_, bottom, LV_ANIM_OFF);
}
void AirChatView::RenderTranscript() {
    if (rendered_revision_ == model_.revision()) {
        Hidden(empty_, !model_.messages().empty());
        return;
    }
    rendered_revision_ = model_.revision();
    const auto& messages = model_.messages();
    uint32_t anchor_id = 0;
    int anchor_y = 0;
    const int scroll_y = lv_obj_get_scroll_y(body_);
    if (!follow_latest_) {
        for (const auto& bubble : bubbles_) {
            if (lv_obj_get_y(bubble.row) + lv_obj_get_height(bubble.row) > scroll_y &&
                std::any_of(messages.begin(), messages.end(),
                            [&](const auto& m) { return m.id == bubble.id; })) {
                anchor_id = bubble.id;
                anchor_y = lv_obj_get_y(bubble.row);
                break;
            }
        }
    }
    // Preserve existing rows (and the scroll anchor) when a sentence is appended.
    for (auto it = bubbles_.begin(); it != bubbles_.end();) {
        if (std::none_of(messages.begin(), messages.end(),
                         [&](const auto& m) { return m.id == it->id; })) {
            lv_obj_delete(it->row);
            it = bubbles_.erase(it);
        } else
            ++it;
    }
    int y = 0;
    for (const auto& message : messages) {
        auto found = std::find_if(bubbles_.begin(), bubbles_.end(),
                                  [&](const auto& b) { return b.id == message.id; });
        const bool user = message.role == AirChatModel::Role::User;
        if (found == bubbles_.end()) {
            auto* row = Box(body_, 0, y, 336, 96);
            auto* author = Label(row, user ? "我" : "小智", user ? 296 : 8, 0, 40);
            lv_obj_set_style_text_align(author, user ? LV_TEXT_ALIGN_RIGHT : LV_TEXT_ALIGN_LEFT, 0);
            auto* surface = Box(row, user ? 96 : 0, 28, user ? 240 : 336, 52, 18);
            lv_obj_set_style_bg_opa(surface, LV_OPA_COVER, 0);
            auto* text = Label(surface, "", 16, 14, user ? 208 : 304, &font_air_chat_18);
            lv_obj_set_style_text_line_space(text, 2, 0);
            auto* accent = user ? nullptr : Box(surface, 16, 0, 28, 4, 2);
            if (accent)
                lv_obj_set_style_bg_opa(accent, LV_OPA_COVER, 0);
            bubbles_.push_back({message.id, message.role, row, author, surface, text, accent});
            found = bubbles_.end() - 1;
        }
        const auto display_text = DisplayText(message.text);
        Text(found->text, display_text.c_str());
        lv_obj_update_layout(found->text);
        const int height = std::max<int32_t>(52, lv_obj_get_height(found->text) + 28);
        lv_obj_set_height(found->surface, height);
        lv_obj_set_y(found->row, y);
        lv_obj_set_height(found->row, height + 44);
        y += height + 44;
    }
    ApplyTheme();
    Hidden(empty_, !messages.empty());
    if (follow_latest_)
        FollowLatest();
    else if (anchor_id) {
        const auto anchor = std::find_if(bubbles_.begin(), bubbles_.end(),
                                         [&](const auto& b) { return b.id == anchor_id; });
        lv_obj_update_layout(body_);
        lv_obj_scroll_to_y(
            body_, std::max(0, scroll_y + static_cast<int>(lv_obj_get_y(anchor->row)) - anchor_y),
            LV_ANIM_OFF);
    }
}
void AirChatView::ApplyTheme() {
    if (!root_)
        return;
    themed_ = true;
    const uint32_t bg = night_ ? 0x08150F : 0xEEF5EC;
    const uint32_t ink = night_ ? 0xE8F1E5 : 0x153D32;
    const uint32_t muted = night_ ? 0xADBEAF : 0x658475;
    const uint32_t soft = night_ ? 0x17372B : 0xDBEED8;
    const uint32_t accent = night_ ? 0xB8E684 : 0x146B55;
    const uint32_t line = night_ ? 0x305644 : 0xD4E4D5;
    Background(root_, bg);
    for (auto* object : {rule_, footer_rule_}) {
        Background(object, line);
        lv_obj_set_style_bg_opa(object, LV_OPA_COVER, 0);
    }
    for (auto* object : {status_pill_, empty_disk_, empty_inner_, latest_, decoration_})
        Background(object, soft);
    for (auto* label : {title_, clock_, status_, empty_title_})
        Color(label, ink);
    Color(lv_obj_get_child(back_, 0), ink);
    for (auto* label : {meta_, online_, empty_hint_})
        Color(label, muted);
    Color(wifi_, connected_ ? ink : muted);
    for (auto* label : {empty_mic_, latest_text_})
        Color(label, accent);
    for (auto* bar : bars_)
        Background(bar, accent);
    Background(action_, accent);
    for (auto* label : {action_text_, action_icon_})
        Color(label, night_ ? 0x153D32 : 0xF1FAEE);
    for (auto& bubble : bubbles_) {
        const bool user = bubble.role == AirChatModel::Role::User;
        Color(bubble.author, muted);
        Background(bubble.surface, user ? (night_ ? 0x145442 : 0x146B55) : soft);
        Color(bubble.text, user ? 0xF1FAEE : ink);
        if (bubble.accent)
            Background(bubble.accent, night_ ? 0xB8E684 : 0xC6EF87);
    }
}
void AirChatView::Event(lv_event_t* event) {
    static_cast<AirChatView*>(lv_event_get_user_data(event))->Handle(event);
}
void AirChatView::GoBack() {
    Close();
    if (callbacks_.back)
        callbacks_.back();
}
bool AirChatView::HandleEdgeGesture(lv_event_t* event) {
    auto* input = lv_indev_active();
    if (!input)
        return false;
    lv_point_t point;
    lv_indev_get_point(input, &point);
    const auto code = lv_event_get_code(event);
    if (code == LV_EVENT_PRESSED) {
        edge_start_ = point;
        edge_candidate_ = point.x >= 0 && point.x < 24;
        ignore_back_click_ = false;
    } else if (code == LV_EVENT_PRESSING || code == LV_EVENT_RELEASED) {
        const int dx = point.x - edge_start_.x, dy = point.y - edge_start_.y;
        if (std::abs(dx) > 10 || std::abs(dy) > 10)
            ignore_back_click_ = true;
        if (dx < -16 || (std::abs(dy) > 10 && std::abs(dy) > std::abs(dx)))
            edge_candidate_ = false;
        if (code == LV_EVENT_RELEASED) {
            const bool back = edge_candidate_ && dx >= 64 && dx > std::abs(dy) * 2;
            edge_candidate_ = false;
            if (back) {
                GoBack();
                return true;
            }
        }
    }
    return false;
}
void AirChatView::Handle(lv_event_t* event) {
    const auto code = lv_event_get_code(event);
    if (code == LV_EVENT_PRESS_LOST || code == LV_EVENT_INDEV_RESET) {
        edge_candidate_ = false;
        ignore_back_click_ = true;
    }
    if (!model_.visible() || !foreground_)
        return;
    auto* target = lv_event_get_current_target_obj(event);
    if (target == root_ && HandleEdgeGesture(event))
        return;
    if (code == LV_EVENT_PRESSED || code == LV_EVENT_PRESSING)
        model_.Interact(Now());
    if (target == body_ && lv_indev_active()) {
        lv_point_t point;
        lv_indev_get_point(lv_indev_active(), &point);
        if (code == LV_EVENT_PRESSED)
            press_start_ = point;
        else if (code == LV_EVENT_PRESSING && std::abs(point.y - press_start_.y) > 10 &&
                 std::abs(point.y - press_start_.y) > std::abs(point.x - press_start_.x)) {
            model_.Browse();
            follow_latest_ = false;
            Hidden(latest_, false);
            Hidden(online_, true);
        }
    }
    if (code != LV_EVENT_CLICKED)
        return;
    model_.Interact(Now());
    if (target == back_) {
        if (!ignore_back_click_)
            GoBack();
    } else if (target == latest_) {
        follow_latest_ = true;
        FollowLatest();
        Hidden(latest_, true);
        Hidden(online_, false);
    } else if (target == action_ && !lv_obj_has_state(action_, LV_STATE_DISABLED)) {
        if (model_.active()) {
            if (!stop_pending_ && callbacks_.stop) {
                stop_pending_ = true;
                callbacks_.stop();
            }
        } else if (enabled_ && connected_ && callbacks_.start) {
            Open(Now(), true);
            callbacks_.start();
        }
    }
}
}  // namespace air
