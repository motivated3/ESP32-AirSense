#include <material_symbols.h>
#include <algorithm>
#include <cstring>
#include <memory>
#include <string>
#include <vector>
#include "air_fonts.h"
#include "air_view.h"
#include "test_support.h"
using namespace air;
namespace {
const char* directory = nullptr;
lv_obj_t* Find(lv_obj_t* root, const char* text, bool visible = false) {
    if (lv_obj_check_type(root, &lv_label_class) && !std::strcmp(lv_label_get_text(root), text) &&
        (!visible || lv_obj_is_visible(root)))
        return root;
    for (uint32_t i = 0; i < lv_obj_get_child_count(root); ++i)
        if (auto* found = Find(lv_obj_get_child(root, i), text, visible))
            return found;
    return nullptr;
}
void Glyphs(lv_obj_t* root) {
    if (lv_obj_check_type(root, &lv_label_class)) {
        const auto* font = lv_obj_get_style_text_font(root, LV_PART_MAIN);
        const auto* text = reinterpret_cast<const unsigned char*>(lv_label_get_text(root));
        while (*text) {
            uint32_t code = *text++;
            if (code >= 0xC0) {
                const int extra = code < 0xE0 ? 1 : code < 0xF0 ? 2 : 3;
                code &= extra == 1 ? 0x1F : extra == 2 ? 0x0F : 7;
                for (int i = 0; i < extra; ++i)
                    code = (code << 6) | (*text++ & 0x3F);
            }
            if (code < 32)
                continue;
            lv_font_glyph_dsc_t glyph{};
            if (!lv_font_get_glyph_dsc(font, &glyph, code, 0) || glyph.is_placeholder) {
                std::fprintf(stderr, "missing glyph U+%04X: %s\n", code, lv_label_get_text(root));
                CHECK(false);
            }
        }
    }
    for (uint32_t i = 0; i < lv_obj_get_child_count(root); ++i)
        Glyphs(lv_obj_get_child(root, i));
}
void Labels(lv_obj_t* root, std::vector<lv_obj_t*>& labels) {
    if (lv_obj_check_type(root, &lv_label_class) &&
        lv_obj_get_style_text_font(root, LV_PART_MAIN) == &font_air_chat_18)
        labels.push_back(root);
    for (uint32_t i = 0; i < lv_obj_get_child_count(root); ++i)
        Labels(lv_obj_get_child(root, i), labels);
}
size_t Objects(lv_obj_t* root) {
    size_t count = 1;
    for (uint32_t i = 0; i < lv_obj_get_child_count(root); ++i)
        count += Objects(lv_obj_get_child(root, i));
    return count;
}
struct Fixture {
    struct Pointer {
        int x = 0, y = 0;
        bool down = false;
    } pointer;
    std::vector<uint32_t> pixels = std::vector<uint32_t>(368 * 448);
    lv_display_t* display = nullptr;
    lv_indev_t* input = nullptr;
    lv_obj_t* screen = nullptr;
    AirUiState state;
    AirSnapshot sample;
    PowerSnapshot power;
    uint64_t now = 1000;
    DeviceState device = kDeviceStateIdle;
    bool connected = true;
    int starts = 0, stops = 0, persisted_voice = 0;
    uint32_t acknowledged = 0;
    std::unique_ptr<AirView> view;
    Fixture() {
        display = lv_display_create(368, 448);
        lv_display_set_color_format(display, LV_COLOR_FORMAT_ARGB8888);
        lv_display_set_buffers(display, pixels.data(), nullptr, pixels.size() * 4,
                               LV_DISPLAY_RENDER_MODE_DIRECT);
        lv_display_set_flush_cb(display, [](lv_display_t* d, const lv_area_t*, uint8_t*) {
            lv_display_flush_ready(d);
        });
        screen = lv_display_get_screen_active(display);
        state.reduce_motion = true;
        AirViewCallbacks callbacks;
        callbacks.now_ms = [&]() { return now; };
        callbacks.wall_time = []() { return std::time_t{1792766160}; };
        callbacks.voice = [&]() { ++starts; };
        callbacks.stop_voice = [&]() { ++stops; };
        callbacks.voice_enabled = [&](bool) { ++persisted_voice; };
        callbacks.acknowledge_alert = [&](uint32_t generation) { acknowledged = generation; };
        view = std::make_unique<AirView>(state, callbacks);
        view->Create(screen);
        input = lv_indev_create();
        lv_indev_set_type(input, LV_INDEV_TYPE_POINTER);
        lv_indev_set_display(input, display);
        lv_indev_set_user_data(input, &pointer);
        lv_indev_set_read_cb(input, [](lv_indev_t* in, lv_indev_data_t* data) {
            const auto& p = *static_cast<Pointer*>(lv_indev_get_user_data(in));
            data->point = {p.x, p.y};
            data->state = p.down ? LV_INDEV_STATE_PRESSED : LV_INDEV_STATE_RELEASED;
        });
        Refresh();
    }
    ~Fixture() {
        lv_indev_delete(input);
        view.reset();
        lv_display_delete(display);
    }
    void Refresh() {
        sample.now_ms = now;
        view->Refresh(sample, power, device, connected, true,
                      connected ? "Wi-Fi 已连接" : "Wi-Fi 离线");
        lv_obj_update_layout(screen);
    }
    void At(uint64_t time) {
        now = time;
        Refresh();
    }
    void Touch(int x, int y, bool down) {
        pointer = {x, y, down};
        lv_tick_inc(40);
        lv_indev_read(input);
        lv_timer_handler();
    }
    void Tap(int x, int y) {
        Touch(x, y, true);
        Touch(x, y, false);
    }
    void Click(const char* text, lv_obj_t* root = nullptr) {
        lv_obj_update_layout(screen);
        auto* label = Find(root ? root : screen, text, true);
        CHECK(label);
        lv_area_t area;
        lv_obj_get_coords(label, &area);
        Tap((area.x1 + area.x2) / 2, (area.y1 + area.y2) / 2);
    }
    void Settle() {
        lv_tick_inc(600);
        lv_timer_handler();
        lv_obj_update_layout(screen);
    }
    lv_obj_t* Chat() {
        auto* title = Find(screen, "小智对话");
        CHECK(title);
        return lv_obj_get_parent(title);
    }
    lv_obj_t* Body() {
        for (uint32_t i = 0; i < lv_obj_get_child_count(Chat()); ++i) {
            auto* object = lv_obj_get_child(Chat(), i);
            if (lv_obj_has_flag(object, LV_OBJ_FLAG_SCROLLABLE) && lv_obj_get_x(object) == 16 &&
                lv_obj_get_y(object) == 112 && lv_obj_get_width(object) == 336)
                return object;
        }
        CHECK(false);
        return nullptr;
    }
    std::vector<lv_obj_t*> Messages() {
        std::vector<lv_obj_t*> labels;
        Labels(Body(), labels);
        return labels;
    }
    bool Visible(const char* text) { return Find(Chat(), text, true) != nullptr; }
    void Open() {
        view->ShowChat();
        Refresh();
        CHECK(view->ChatVisible() && lv_obj_is_visible(Chat()));
    }
    void History(int count = 12) {
        for (int i = 0; i < count; ++i) {
            const auto text = "历史消息" + std::to_string(i);
            view->SetChatMessage("user", text.c_str());
        }
        Open();
        CHECK(lv_obj_get_scroll_bottom(Body()) <= 1);
    }
    void Browse(bool text) {
        auto* body = Body();
        lv_obj_scroll_to_y(body, 0, LV_ANIM_OFF);
        lv_obj_update_layout(screen);
        int x = 18, y = 262;  // Blank area left of a user bubble.
        if (text) {
            const auto labels = Messages();
            CHECK(labels.size() > 1);
            lv_area_t area;
            lv_obj_get_coords(labels[1], &area);
            x = area.x1 + 12;
            y = (area.y1 + area.y2) / 2;
        }
        Touch(x, y, true);
        Touch(x, y - 20, true);
        Touch(x, y - 40, true);
        Touch(x, y - 64, true);
        CHECK(lv_obj_get_scroll_y(body) > 20);
        Touch(x, y - 64, false);
        Settle();
        CHECK(Visible("回到最新"));
    }
    void Render(const char* name) {
        Glyphs(Chat());
        lv_obj_invalidate(screen);
        lv_refr_now(display);
        if (!directory)
            return;
        const auto path = std::string(directory) + "/" + name + ".ppm";
        auto* file = std::fopen(path.c_str(), "wb");
        CHECK(file);
        std::fprintf(file, "P6\n368 448\n255\n");
        for (auto pixel : pixels) {
            const uint8_t rgb[] = {static_cast<uint8_t>(pixel >> 16),
                                   static_cast<uint8_t>(pixel >> 8), static_cast<uint8_t>(pixel)};
            CHECK(std::fwrite(rgb, 1, 3, file) == 3);
        }
        CHECK(std::fclose(file) == 0);
    }
};
void MicrophoneAndFooter() {
    Fixture f;
    CHECK(!f.view->ChatVisible());
    f.Click(MATERIAL_SYMBOLS_MIC);
    f.Refresh();
    CHECK(f.view->ChatVisible() && f.starts == 1);
    CHECK(f.Visible("暂无对话记录") && f.Visible("开始说话") && f.Visible("对话结束"));
    auto* body = f.Body();
    CHECK(lv_obj_get_x(body) == 16 && lv_obj_get_y(body) == 112);
    CHECK(lv_obj_get_width(body) == 336 && lv_obj_get_height(body) == 260);
    auto* action = lv_obj_get_parent(Find(f.Chat(), "开始说话"));
    CHECK(lv_obj_get_x(action) == 244 && lv_obj_get_y(action) == 388);
    CHECK(lv_obj_get_width(action) == 108 && lv_obj_get_height(action) == 48);
    f.Click("开始说话", f.Chat());
    CHECK(f.starts == 2 && f.stops == 0);
    f.device = kDeviceStateListening;
    f.Refresh();
    CHECK(f.Visible("正在聆听") && f.Visible("停止") && f.Visible("你说，我在听"));
    f.Render("chat-listening");
    f.view->WakeHome();
    f.Refresh();
    CHECK(!f.view->ChatVisible() && f.stops == 0);
    f.Click(MATERIAL_SYMBOLS_MIC);
    f.Refresh();
    CHECK(f.view->ChatVisible() && f.starts == 2);
}
void TranscriptAndStreaming() {
    Fixture f;
    f.Open();
    f.view->SetChatMessage("assistant", "正在连接");
    f.Refresh();
    CHECK(f.Messages().size() == 1);
    f.view->RemoveChatMessage("user", "正在连接");
    f.Refresh();
    CHECK(f.Messages().size() == 1);
    f.view->RemoveChatMessage("assistant", "正在连接");
    f.Refresh();
    CHECK(f.Messages().empty());
    f.view->SetChatMessage("user", "车里空气怎么样？");
    f.device = kDeviceStateListening;
    f.Refresh();
    CHECK(f.Visible("正在思考") && !f.Visible("暂无对话记录"));
    f.view->SetChatMessage("assistant", "目前空气质量不错，");
    f.Refresh();
    CHECK(f.Messages().size() == 2);
    auto* answer = f.Messages().back();
    auto* row = lv_obj_get_child(f.Body(), 1);
    f.view->SetChatMessage("assistant", "继续保持适当通风。");
    f.device = kDeviceStateSpeaking;
    f.Refresh();
    CHECK(f.Messages().size() == 2 && f.Messages().back() == answer &&
          lv_obj_get_child(f.Body(), 1) == row);
    CHECK(!std::strcmp(lv_label_get_text(answer), "目前空气质量不错，\n继续保持适当通风。"));
    CHECK(f.Visible("正在回复"));
    f.view->SetChatMessage("system", "不可见");
    f.view->SetChatMessage("user", " \t\r\n");
    f.view->SetChatMessage(nullptr, "不可见");
    f.view->SetChatMessage("user", nullptr);
    f.Refresh();
    CHECK(f.Messages().size() == 2 && !Find(f.Chat(), "不可见"));
    f.Render("chat-conversation-day");
    f.state.SetTheme(true);
    f.Refresh();
    CHECK(lv_color_eq(lv_obj_get_style_bg_color(f.Chat(), LV_PART_MAIN), lv_color_hex(0x08150F)));
    f.Render("chat-conversation-night");
    f.device = kDeviceStateListening;
    f.Refresh();
    CHECK(f.Visible("正在聆听") && f.Messages().size() == 2);
    f.Render("chat-listening-history");
}
void IdleDeadline() {
    Fixture f;
    f.view->Navigate(Page::Trend, false);
    f.view->SetChatMessage("user", "保留记录");
    f.Open();
    f.At(30999);
    CHECK(f.view->ChatVisible());
    f.At(31000);
    CHECK(!f.view->ChatVisible() && f.state.page() == Page::Home);
    f.Open();
    CHECK(Find(f.Chat(), "保留记录"));
}
void BackBeforeActivePoll() {
    Fixture f;
    f.Click(MATERIAL_SYMBOLS_MIC);
    CHECK(f.view->ChatVisible() && f.starts == 1);
    f.Click(MATERIAL_SYMBOLS_ARROW_BACK, f.Chat());
    CHECK(!f.view->ChatVisible());
    f.device = kDeviceStateConnecting;
    f.Refresh();
    CHECK(!f.view->ChatVisible());
    f.device = kDeviceStateListening;
    f.Refresh();
    CHECK(!f.view->ChatVisible());
    f.device = kDeviceStateIdle;
    f.Refresh();
    f.device = kDeviceStateListening;
    f.Refresh();
    CHECK(f.view->ChatVisible());
}
void ActiveAndManualBack() {
    Fixture f;
    for (auto state : {kDeviceStateConnecting, kDeviceStateListening, kDeviceStateSpeaking}) {
        f.device = state;
        f.Refresh();
        CHECK(f.view->ChatVisible());
        f.At(f.now + 100000);
        CHECK(f.view->ChatVisible());
    }
    f.Click(MATERIAL_SYMBOLS_ARROW_BACK, f.Chat());
    CHECK(!f.view->ChatVisible() && f.stops == 0);
    for (auto state : {kDeviceStateConnecting, kDeviceStateListening, kDeviceStateSpeaking}) {
        f.device = state;
        f.At(f.now + 100);
        CHECK(!f.view->ChatVisible());
    }
    f.Open();
    CHECK(f.stops == 0 && f.starts == 0);
    f.view->WakeHome();
    f.Refresh();
    CHECK(!f.view->ChatVisible());
    f.device = kDeviceStateIdle;
    f.Refresh();
    f.device = kDeviceStateListening;
    f.Refresh();
    CHECK(f.view->ChatVisible());
    f.device = kDeviceStateIdle;
    f.Refresh();
    const auto idle = f.now;
    f.At(idle + 29999);
    CHECK(f.view->ChatVisible());
    f.At(idle + 30000);
    CHECK(!f.view->ChatVisible());
}
void EdgeBackWaitsForRelease() {
    for (const auto start : {lv_point_t{6, 262}, lv_point_t{18, 262}, lv_point_t{10, 36}}) {
        Fixture f;
        f.view->Navigate(Page::Trend, false);
        f.view->SetChatMessage("assistant", "保留对话和语音状态");
        f.Click(MATERIAL_SYMBOLS_MIC);
        f.Refresh();
        CHECK(f.view->ChatVisible() && f.starts == 1);
        f.Touch(start.x, start.y, true);
        f.Touch(start.x + 32, start.y, true);
        f.Touch(start.x + 64, start.y, true);
        CHECK(f.view->ChatVisible());  // A drag never changes pages before release.
        f.Touch(start.x + 64, start.y, false);
        CHECK(!f.view->ChatVisible() && f.state.page() == Page::Home);
        CHECK(f.starts == 1 && f.stops == 0 && f.persisted_voice == 0 && f.state.voice_enabled);
        for (auto state : {kDeviceStateConnecting, kDeviceStateListening, kDeviceStateSpeaking}) {
            f.device = state;
            f.Refresh();
            CHECK(!f.view->ChatVisible());  // Same pending-start suppression as the Back button.
        }
        f.device = kDeviceStateIdle;
        f.Refresh();
        f.device = kDeviceStateListening;
        f.Refresh();
        CHECK(f.view->ChatVisible() && Find(f.Chat(), "保留对话和语音状态"));
        f.Touch(start.x, start.y, true);
        f.Touch(start.x + 80, start.y, true);
        CHECK(f.view->ChatVisible());
        f.Touch(start.x + 80, start.y, false);
        f.Refresh();
        CHECK(!f.view->ChatVisible() && f.stops == 0);  // An active voice session continues.
    }
    Fixture f;
    for (int x : {10, 54}) {
        f.Open();
        f.Tap(x, 36);  // Both edges of the existing 48px Back target remain clickable.
        CHECK(!f.view->ChatVisible() && f.state.page() == Page::Home);
    }
}
void EdgeBackRejectsOtherDrags() {
    struct Drag {
        lv_point_t start, middle, finish;
    };
    const Drag drags[] = {
        {{24, 262}, {56, 262}, {104, 262}},  // The edge strip ends before x=24.
        {{80, 262}, {112, 262}, {160, 262}}, {{6, 262}, {36, 262}, {69, 262}},  // Less than 64px.
        {{18, 262}, {10, 262}, {0, 262}},    {{6, 262}, {6, 230}, {6, 182}},
        {{6, 262}, {46, 242}, {86, 222}},   // Horizontal motion must exceed 2x vertical.
        {{6, 262}, {10, 220}, {106, 262}},  // Vertical intent cannot turn into a Back swipe.
        {{6, 262}, {6, 250}, {106, 250}},   // Match the transcript's 10px browse threshold.
        {{10, 36}, {42, 36}, {73, 36}},     // A short drag over Back is not a button click.
        {{10, 36}, {10, 70}, {100, 70}},    // A vertical header drag must not click Back either.
    };
    for (const auto& drag : drags) {
        Fixture f;
        f.view->Navigate(Page::Trend, false);
        f.Open();
        f.Touch(drag.start.x, drag.start.y, true);
        f.Touch(drag.middle.x, drag.middle.y, true);
        f.Touch(drag.finish.x, drag.finish.y, true);
        CHECK(f.view->ChatVisible());
        f.Touch(drag.finish.x, drag.finish.y, false);
        CHECK(f.view->ChatVisible() && f.state.page() == Page::Trend && f.stops == 0);
    }
}
void EdgeBackCancelsAcrossInterruptions() {
    {
        Fixture f;
        f.Open();
        f.Touch(6, 262, true);
        CHECK(lv_obj_send_event(f.Chat(), LV_EVENT_PRESS_LOST, f.input) == LV_RESULT_OK);
        f.Touch(86, 262, true);
        f.Touch(86, 262, false);
        CHECK(f.view->ChatVisible());
        f.Touch(6, 262, true);
        f.Touch(38, 262, true);
        f.view->WakeHome();
        f.Open();
        f.Touch(86, 262, true);
        f.Touch(86, 262, false);
        CHECK(f.view->ChatVisible());
    }
    for (int obstruction = 0; obstruction < 2; ++obstruction) {
        Fixture f;
        f.Open();
        f.Touch(6, 262, true);
        f.Touch(70, 262, true);
        CHECK(f.view->ChatVisible());
        if (obstruction == 0)
            f.view->RequestAction(DeviceAction::Shutdown);
        else if (obstruction == 1)
            f.state.SetDisplayOn(false);
        if (obstruction != 0)
            f.Refresh();  // Confirmation can arrive between periodic display refreshes.
        f.Touch(86, 262, false);
        CHECK(f.view->ChatVisible() && f.stops == 0);
        if (obstruction == 0) {
            CHECK(Find(f.screen, "确认关机？", true));
            f.Click("取消");
        } else if (obstruction == 1)
            f.state.SetDisplayOn(true);
        f.Refresh();
        CHECK(f.view->ChatVisible());
        f.Touch(6, 262, true);
        f.Touch(86, 262, true);
        f.Touch(86, 262, false);
        CHECK(!f.view->ChatVisible());  // A fresh gesture works after the interruption ends.
    }
}
void EdgeVerticalBrowseKeepsChatOpen() {
    Fixture f;
    f.History();
    auto* body = f.Body();
    lv_obj_scroll_to_y(body, 0, LV_ANIM_OFF);
    lv_obj_update_layout(f.screen);
    f.Touch(18, 262, true);  // Starts inside the edge strip over the conversation body.
    f.Touch(18, 242, true);
    f.Touch(18, 222, true);
    CHECK(lv_obj_get_scroll_y(body) > 20);
    f.Touch(118, 222, true);  // A later horizontal move must retain the vertical browse intent.
    f.Touch(118, 222, false);
    f.Settle();
    CHECK(f.view->ChatVisible() && f.Visible("回到最新"));
    f.At(100000);
    CHECK(f.view->ChatVisible());  // Manual browse still cancels the idle return deadline.
}
void TouchRestartsDeadline() {
    Fixture f;
    f.Open();
    f.At(30999);
    f.Tap(180, 90);  // Header background, no action.
    f.At(31000);
    CHECK(f.view->ChatVisible());
    f.At(60998);
    CHECK(f.view->ChatVisible());
    f.At(60999);
    CHECK(!f.view->ChatVisible());
}
void BrowseText() {
    Fixture f;
    f.History();
    f.Browse(true);
    auto* body = f.Body();
    const auto scroll = lv_obj_get_scroll_y(body);
    f.view->SetChatMessage("assistant", "新回复不能抢走正在翻看的记录。");
    f.Refresh();
    CHECK(lv_obj_get_scroll_y(body) == scroll && lv_obj_get_scroll_bottom(body) > 0);
    CHECK(f.Visible("回到最新"));
    f.Render("chat-browsing");
    f.At(100000);
    CHECK(f.view->ChatVisible());
    f.Click("回到最新", f.Chat());
    CHECK(!f.Visible("回到最新") && lv_obj_get_scroll_bottom(body) <= 1);
    f.view->SetChatMessage("user", "现在继续对话");
    f.Refresh();
    CHECK(lv_obj_get_scroll_bottom(body) <= 1);
    f.At(200000);
    CHECK(f.view->ChatVisible());  // Latest restores following, not the deadline.
    f.Open();
    f.At(230000);
    CHECK(!f.view->ChatVisible());
}
void BrowseBackgroundAndNewSession() {
    Fixture f;
    f.History();
    f.Browse(false);
    f.At(100000);
    CHECK(f.view->ChatVisible());
    f.device = kDeviceStateListening;
    f.Refresh();
    CHECK(f.view->ChatVisible() && !f.Visible("回到最新"));
    CHECK(lv_obj_get_scroll_bottom(f.Body()) <= 1);
    f.device = kDeviceStateIdle;
    f.Refresh();
    f.At(129999);
    CHECK(f.view->ChatVisible());
    f.At(130000);
    CHECK(!f.view->ChatVisible());
}
void StopOnceWithoutDisablingVoice() {
    for (auto state : {kDeviceStateConnecting, kDeviceStateListening, kDeviceStateSpeaking}) {
        Fixture f;
        f.device = state;
        f.Refresh();
        CHECK(f.view->ChatVisible());
        f.Click("停止", f.Chat());
        f.Click("停止", f.Chat());
        CHECK(f.stops == 1 && f.starts == 0 && f.persisted_voice == 0 && f.state.voice_enabled);
        f.Refresh();
        CHECK(f.Visible("正在停止"));
        f.Click("停止", f.Chat());
        CHECK(f.stops == 1);
        f.device = kDeviceStateIdle;
        f.Refresh();
        CHECK(f.Visible("对话结束") && f.Visible("开始说话"));
        f.device = kDeviceStateListening;
        f.Refresh();
        CHECK(f.Visible("正在聆听") && f.state.voice_enabled);
        f.Click("停止", f.Chat());
        CHECK(f.stops == 2 && f.persisted_voice == 0);
    }
}
void OfflineAndDisabled() {
    Fixture f;
    f.connected = false;
    f.Refresh();
    f.Click(MATERIAL_SYMBOLS_MIC);
    f.Refresh();
    CHECK(f.view->ChatVisible() && f.starts == 0);
    CHECK(f.Visible("离线") && f.Visible("语音离线") && f.Visible("请先连接Wi-Fi"));
    f.Click("开始说话", f.Chat());
    CHECK(f.starts == 0 && f.stops == 0);
    f.Render("chat-offline");
    f.state.voice_enabled = false;
    f.connected = true;
    f.Refresh();
    CHECK(f.Visible("语音已关闭"));
    f.Click("开始说话", f.Chat());
    CHECK(f.starts == 0 && f.persisted_voice == 0);
    f.Render("chat-voice-disabled");
    f.view->WakeHome();
    f.device = kDeviceStateListening;
    f.Refresh();
    CHECK(!f.view->ChatVisible());
    f.power.shutting_down = true;
    f.Refresh();
    f.view->ShowChat();
    CHECK(!f.view->ChatVisible());
}
void ForegroundSuspendsDeadline() {
    for (int obstruction = 0; obstruction < 2; ++obstruction) {
        Fixture f;
        f.Open();
        f.At(30999);
        if (obstruction == 0)
            f.view->RequestAction(DeviceAction::Shutdown);
        else if (obstruction == 1)
            f.state.SetDisplayOn(false);
        f.Refresh();
        f.At(obstruction == 0 ? 32000 : 100000);
        CHECK(f.view->ChatVisible());
        if (obstruction == 0)
            f.Click("取消");
        else if (obstruction == 1)
            f.state.SetDisplayOn(true);
        f.Refresh();
        const auto resumed = f.now;
        f.At(resumed + 29999);
        CHECK(f.view->ChatVisible());
        f.At(resumed + 30000);
        CHECK(!f.view->ChatVisible());
    }
}
void AlarmDoesNotInterruptChat() {
    Fixture f;
    f.view->SetChatMessage("user", "告警后仍保留这条记录");
    f.device = kDeviceStateSpeaking;
    f.Refresh();
    f.sample.scd.ppm = 2400;
    f.sample.co2.has_value = f.sample.co2.connected = f.sample.co2.ready = true;
    f.sample.co2.within_spec = true;
    f.view->SetAlerts({19, kAlertCo2, 0, kAlertCo2}, f.sample, f.power);
    f.Refresh();
    CHECK(f.view->ChatVisible() && !Find(f.screen, "知道了", true));
    f.Tap(295, 411);
    CHECK(f.stops == 1);  // Concentration alerts must not intercept the stop button.
    f.view->ShowChat();
    f.view->SetAlerts({20, kAlertCo2, 0, kAlertCo2}, f.sample, f.power);
    f.Refresh();
    f.Render("chat-with-concentration-alert");
    f.Refresh();
    CHECK(f.view->ChatVisible() && !Find(f.screen, "知道了", true));
    CHECK(Find(f.Chat(), "告警后仍保留这条记录") && f.stops == 1 && f.acknowledged == 0);
}
void UnsupportedGlyphPaintsVisibleReplacement() {
    Fixture f;
    f.Open();
    f.view->SetChatMessage("user", "🙂");
    f.Refresh();
    auto* label = Find(f.Chat(), "�");
    CHECK(label && lv_obj_is_visible(label));
    f.Render("chat-glyph-fallback");
    lv_area_t area;
    lv_obj_get_coords(label, &area);
    const auto foreground =
        lv_color_to_u32(lv_obj_get_style_text_color(label, LV_PART_MAIN)) & 0xFFFFFF;
    size_t ink = 0;
    for (int y = std::max(0, static_cast<int>(area.y1));
         y <= std::min(447, static_cast<int>(area.y2)); ++y)
        for (int x = std::max(0, static_cast<int>(area.x1));
             x <= std::min(367, static_cast<int>(area.x2)); ++x)
            if ((f.pixels[y * 368 + x] & 0xFFFFFF) == foreground)
                ++ink;
    CHECK(ink > 8);  // A supported codepoint must also produce visible pixels, not a blank cell.
}
void BodyLineSpacing() {
    Fixture f;
    f.Open();
    f.view->SetChatMessage("assistant", "第一行\n第二行");
    f.Refresh();
    auto* fallback = Find(f.Chat(), "第一行\n第二行");
    CHECK(fallback);
    lv_point_t measured;
    lv_text_get_size(&measured, "第一行\n第二行", &font_air_chat_18, 0,
                     lv_obj_get_style_text_line_space(fallback, LV_PART_MAIN), 304,
                     LV_TEXT_FLAG_NONE);
    CHECK(measured.y == 52);  // 25px font with 27px baseline spacing in the approved mockup.
}
void WaveformLifecycle() {
    Fixture f;
    auto* timer = lv_anim_get_timer();
    lv_timer_set_period(timer, 16);  // Match this board's CONFIG_LV_DEF_REFR_PERIOD.
    f.state.reduce_motion = false;
    f.device = kDeviceStateListening;
    f.Refresh();
    auto* pill = lv_obj_get_parent(Find(f.Chat(), "正在聆听"));
    int heights[5];
    for (int i = 0; i < 5; ++i)
        heights[i] = lv_obj_get_style_height(lv_obj_get_child(pill, i), LV_PART_MAIN);
    bool moved = false;
    for (int frame = 0; frame < 90; ++frame) {
        lv_tick_inc(16);
        lv_timer_handler();
        lv_obj_update_layout(f.screen);
        for (int i = 0; i < 5; ++i) {
            const int height = lv_obj_get_style_height(lv_obj_get_child(pill, i), LV_PART_MAIN);
            if (std::abs(height - heights[i]) > 3)
                std::fprintf(stderr, "wave discontinuity: frame=%d bar=%d before=%d after=%d\n",
                             frame, i, heights[i], height);
            CHECK(std::abs(height - heights[i]) <= 3);
            moved |= height != heights[i];
            heights[i] = height;
        }
        if (directory && frame % 3 == 0)
            f.Render(("chat-wave-" + std::to_string(frame / 3)).c_str());
    }
    CHECK(moved);
    f.state.reduce_motion = true;
    f.Refresh();
    for (int i = 0; i < 5; ++i)
        heights[i] = lv_obj_get_style_height(lv_obj_get_child(pill, i), LV_PART_MAIN);
    f.Settle();
    for (int i = 0; i < 5; ++i)
        CHECK(lv_obj_get_style_height(lv_obj_get_child(pill, i), LV_PART_MAIN) == heights[i]);
    f.state.reduce_motion = false;
    f.Refresh();
    f.view->WakeHome();
    for (int i = 0; i < 5; ++i)
        heights[i] = lv_obj_get_style_height(lv_obj_get_child(pill, i), LV_PART_MAIN);
    f.Settle();
    for (int i = 0; i < 5; ++i)
        CHECK(lv_obj_get_style_height(lv_obj_get_child(pill, i), LV_PART_MAIN) == heights[i]);
    lv_timer_set_period(timer, LV_DEF_REFR_PERIOD);
}
void BrowseSurvivingAnchor() {
    Fixture f;
    f.History(16);
    f.Browse(true);
    lv_obj_scroll_to_y(f.Body(), 220, LV_ANIM_OFF);
    lv_obj_update_layout(f.screen);
    auto* anchor = Find(f.Chat(), "历史消息3");
    CHECK(anchor && lv_obj_is_visible(anchor));
    lv_area_t before, after;
    lv_obj_get_coords(anchor, &before);
    CHECK(before.y1 >= 112 && before.y2 < 372);
    f.view->SetChatMessage("user", "新消息淘汰最旧记录");
    f.Refresh();
    CHECK(f.Messages().size() == 16 && Find(f.Chat(), "历史消息3") == anchor);
    lv_obj_get_coords(anchor, &after);
    CHECK(after.y1 == before.y1 && after.y2 == before.y2);
}
void LongTextBoundsAndGlyphs() {
    Fixture f;
    f.Open();
    const char* broad = "导航到附近的新能源汽车充电站，请确认二氧化碳和甲醛浓度，适当开窗通风。";
    f.view->SetChatMessage("user", broad);
    f.view->SetChatMessage("assistant", "支持常用中文，表情🙂替换为清晰标记。");
    f.Refresh();
    CHECK(Find(f.Chat(), broad));
    auto* fallback = Find(f.Chat(), "支持常用中文，表情�替换为清晰标记。");
    CHECK(fallback && lv_obj_is_visible(fallback));
    Glyphs(f.Chat());
    CHECK(lv_obj_get_style_text_font(fallback, LV_PART_MAIN) == &font_air_chat_18 &&
          font_air_chat_18.line_height == 25);
    f.view->SetChatMessage("user", "A\xf0\x28\x8c\x28Z");
    f.Refresh();
    CHECK(Find(f.Chat(), "A?(?(Z"));
    const std::string huge(100000, 'A');
    f.view->SetChatMessage("user", huge.c_str());
    f.Refresh();
    size_t bytes = 0;
    for (auto* label : f.Messages()) {
        const auto length = std::strlen(lv_label_get_text(label));
        CHECK(length <= 768);
        if (lv_label_get_text(label)[0] == 'A' && length > 10)
            bytes += length;
    }
    CHECK(bytes == 4096);
    std::string chinese;
    for (int i = 0; i < 300; ++i)
        chinese += "空气";
    for (int i = 0; i < 30; ++i) {
        f.view->SetChatMessage(i % 2 ? "assistant" : "user", chinese.c_str());
        f.Refresh();
        CHECK(f.Messages().size() <= 16 && lv_obj_get_child_count(f.Body()) <= 16);
    }
    CHECK(f.Messages().size() == 16);
    const size_t widgets = Objects(f.Chat());
    for (int i = 0; i < 100; ++i) {
        f.view->SetChatMessage(i % 2 ? "assistant" : "user", chinese.c_str());
        f.Refresh();
        CHECK(f.Messages().size() == 16 && Objects(f.Chat()) <= widgets + 1);
    }
    int previous_bottom = -1;
    for (uint32_t i = 0; i < lv_obj_get_child_count(f.Body()); ++i) {
        auto* row = lv_obj_get_child(f.Body(), i);
        CHECK(lv_obj_get_y(row) > previous_bottom);
        previous_bottom = lv_obj_get_y(row) + lv_obj_get_height(row) - 1;
    }
    for (auto* label : f.Messages()) {
        CHECK(std::strlen(lv_label_get_text(label)) <= 768 &&
              lv_label_get_long_mode(label) == LV_LABEL_LONG_WRAP);
        lv_area_t text, surface;
        lv_obj_get_coords(label, &text);
        lv_obj_get_coords(lv_obj_get_parent(label), &surface);
        CHECK(text.x1 >= surface.x1 && text.x2 <= surface.x2 && text.y1 >= surface.y1 &&
              text.y2 <= surface.y2);
    }
    CHECK(lv_obj_get_scroll_bottom(f.Body()) <= 1);
    auto* footer = lv_obj_get_parent(Find(f.Chat(), "开始说话"));
    CHECK(lv_obj_get_y(footer) == 388 && lv_obj_get_height(footer) == 48);
    f.Render("chat-long-text");
}
}  // namespace
int main(int argc, char** argv) {
    lv_init();
    directory = argc > 1 && std::strcmp(argv[1], "-") ? argv[1] : nullptr;
    struct Test {
        const char* name;
        void (*run)();
    };
    const Test tests[] = {{"microphone", MicrophoneAndFooter},
                          {"transcript", TranscriptAndStreaming},
                          {"idle", IdleDeadline},
                          {"pending-back", BackBeforeActivePoll},
                          {"active-back", ActiveAndManualBack},
                          {"edge-back", EdgeBackWaitsForRelease},
                          {"edge-rejected", EdgeBackRejectsOtherDrags},
                          {"edge-cancelled", EdgeBackCancelsAcrossInterruptions},
                          {"edge-browse", EdgeVerticalBrowseKeepsChatOpen},
                          {"touch", TouchRestartsDeadline},
                          {"browse-text", BrowseText},
                          {"browse-background", BrowseBackgroundAndNewSession},
                          {"browse-anchor", BrowseSurvivingAnchor},
                          {"stop", StopOnceWithoutDisablingVoice},
                          {"offline", OfflineAndDisabled},
                          {"foreground", ForegroundSuspendsDeadline},
                          {"alarm", AlarmDoesNotInterruptChat},
                          {"glyph-paint", UnsupportedGlyphPaintsVisibleReplacement},
                          {"line-spacing", BodyLineSpacing},
                          {"waveform", WaveformLifecycle},
                          {"long-text", LongTextBoundsAndGlyphs}};
    size_t count = 0;
    for (const auto& test : tests) {
        if (argc > 2 && std::strcmp(argv[2], test.name))
            continue;
        std::printf("chat_view: %s\n", test.name);
        std::fflush(stdout);
        test.run();
        ++count;
    }
    CHECK(count != 0);
    std::printf("chat_view: %zu native layout, pointer, timing and conversation checks passed\n",
                count);
}
