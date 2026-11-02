#include "air_controls.h"
namespace air {
std::optional<bool> DebouncedInput::Update(bool pressed, uint64_t now_ms, bool valid) {
    if (!valid || (sampled_ && (now_ms < sampled_ms_ || now_ms - sampled_ms_ > 100))) {
        sampled_ = initialized_ = false;
    }
    if (!valid)
        return {};
    if (!sampled_ || pressed != candidate_) {
        candidate_ = pressed;
        changed_ms_ = now_ms;
    }
    sampled_ = true;
    sampled_ms_ = now_ms;
    if (now_ms - changed_ms_ >= 30) {
        stable_ = candidate_;
        initialized_ = true;
    }
    if (!initialized_)
        return {};
    return stable_;
}
ButtonAction InputPolicy::Update(ButtonId button, bool pressed, uint64_t now_ms, bool valid) {
    auto& key = keys_[static_cast<unsigned>(button)];
    const bool gap = button == ButtonId::Power && key.sampled &&
                     (now_ms < key.sample_ms || now_ms - key.sample_ms > 100);
    if (!valid || gap) {
        key = {};
        key.sampled = valid;
        key.sample_ms = now_ms;
        key.armed = valid && !pressed;
        return ButtonAction::None;
    }
    key.sampled = true;
    key.sample_ms = now_ms;
    if (!key.armed) {
        if (!pressed)
            key.armed = true;
        return ButtonAction::None;
    }
    if (pressed && !key.pressed) {
        key.pressed = true;
        key.consumed = false;
        key.down_ms = now_ms;
    }
    if (pressed && button == ButtonId::Power && !key.consumed && now_ms - key.down_ms >= 3000) {
        key.consumed = true;
        return ButtonAction::Shutdown;
    }
    if (!pressed && key.pressed) {
        key.pressed = false;
        if (!key.consumed)
            return button == ButtonId::Boot ? ButtonAction::WakeHome : ButtonAction::ToggleDisplay;
    }
    return ButtonAction::None;
}
PendingAction ActionGate::Request(DeviceAction action, uint64_t now_ms) {
    pending_ = PendingAction{++next_id_, action, now_ms + 30000};
    return *pending_;
}
std::optional<DeviceAction> ActionGate::Confirm(uint64_t id, uint64_t now_ms) {
    if (!pending_ || pending_->id != id)
        return {};
    auto pending = *pending_;
    pending_.reset();
    if (now_ms >= pending.expires_ms)
        return {};
    return pending.action;
}
void ActionGate::Cancel(uint64_t id) {
    if (pending_ && pending_->id == id)
        pending_.reset();
}
bool CanToggleVoice(DeviceState state, bool connected, bool enabled) {
    return connected && enabled &&
           (state == kDeviceStateIdle || state == kDeviceStateListening ||
            state == kDeviceStateSpeaking);
}
}  // namespace air
