#pragma once
#include <cstdint>
#include <optional>
#include "device_state.h"

namespace air {
enum class ButtonId { Boot, Power };
enum class ButtonAction { None, WakeHome, ToggleDisplay, Shutdown };
class DebouncedInput {
public:
    std::optional<bool> Update(bool pressed, uint64_t now_ms, bool valid);

private:
    bool sampled_ = false;
    bool initialized_ = false;
    bool candidate_ = false;
    bool stable_ = false;
    uint64_t changed_ms_ = 0;
    uint64_t sampled_ms_ = 0;
};
class InputPolicy {
public:
    ButtonAction Update(ButtonId button, bool pressed, uint64_t now_ms, bool valid);

private:
    struct Key {
        bool armed = false;
        bool pressed = false;
        bool consumed = false;
        bool sampled = false;
        uint64_t down_ms = 0;
        uint64_t sample_ms = 0;
    } keys_[2];
};
enum class DeviceAction { ConfigureWifi, Shutdown };
struct PendingAction {
    uint64_t id;
    DeviceAction action;
    uint64_t expires_ms;
};
class ActionGate {
public:
    PendingAction Request(DeviceAction action, uint64_t now_ms);
    std::optional<DeviceAction> Confirm(uint64_t id, uint64_t now_ms);
    void Cancel(uint64_t id);

private:
    uint64_t next_id_ = 0;
    std::optional<PendingAction> pending_;
};
bool CanToggleVoice(DeviceState state, bool connected, bool enabled);
}  // namespace air
