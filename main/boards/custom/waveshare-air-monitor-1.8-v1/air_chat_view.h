#pragma once
#include <lvgl.h>
#include <ctime>
#include <functional>
#include <vector>
#include "air_chat_model.h"
#include "device_state.h"

namespace air {
class AirChatView {
public:
    struct Callbacks {
        std::function<uint64_t()> now_ms;
        std::function<void()> back, start, stop;
    };
    explicit AirChatView(Callbacks callbacks) : callbacks_(std::move(callbacks)) {}
    ~AirChatView();
    void Create(lv_obj_t* parent);
    void Open(uint64_t now_ms, bool voice_intent = false);
    void Close();
    bool visible() const { return model_.visible(); }
    void Append(const char* role, const char* text);
    void Remove(const char* role, const char* text);
    bool Update(DeviceState state, bool connected, bool enabled, bool night, bool reduce_motion,
                bool foreground, uint64_t now_ms, std::time_t wall_time);
    void StopAnimation();
    void Suspend(uint64_t now_ms) {
        edge_candidate_ = false;
        ignore_back_click_ = true;
        model_.Tick(now_ms, false);
        StopAnimation();
    }

private:
    struct Bubble {
        uint32_t id;
        AirChatModel::Role role;
        lv_obj_t *row, *author, *surface, *text, *accent;
    };
    static void Event(lv_event_t* event);
    void Handle(lv_event_t* event);
    bool HandleEdgeGesture(lv_event_t* event);
    void GoBack();
    void RenderTranscript();
    void ApplyTheme();
    void FollowLatest();
    uint64_t Now() const { return callbacks_.now_ms ? callbacks_.now_ms() : 0; }
    Callbacks callbacks_;
    AirChatModel model_;
    std::vector<Bubble> bubbles_;
    uint32_t rendered_revision_ = UINT32_MAX;
    DeviceState state_ = kDeviceStateStarting;
    bool night_ = false, themed_ = false, follow_latest_ = true;
    bool stop_pending_ = false, awaiting_reply_ = false, animating_ = false;
    bool pending_start_ = false, suppress_pending_start_ = false;
    bool connected_ = false, enabled_ = true;
    bool foreground_ = true, edge_candidate_ = false, ignore_back_click_ = true;
    lv_point_t press_start_{};
    lv_point_t edge_start_{};
    lv_obj_t *root_ = nullptr, *decoration_ = nullptr, *back_ = nullptr, *title_ = nullptr,
             *clock_ = nullptr;
    lv_obj_t *wifi_ = nullptr, *rule_ = nullptr, *meta_ = nullptr, *online_ = nullptr;
    lv_obj_t *body_ = nullptr, *empty_ = nullptr, *empty_disk_ = nullptr;
    lv_obj_t* empty_inner_ = nullptr;
    lv_obj_t *empty_mic_ = nullptr, *empty_title_ = nullptr, *empty_hint_ = nullptr;
    lv_obj_t *latest_ = nullptr, *latest_text_ = nullptr, *footer_rule_ = nullptr;
    lv_obj_t *status_pill_ = nullptr, *status_ = nullptr, *action_ = nullptr;
    lv_obj_t *action_icon_ = nullptr, *action_text_ = nullptr;
    lv_obj_t* bars_[5]{};
};
}  // namespace air
