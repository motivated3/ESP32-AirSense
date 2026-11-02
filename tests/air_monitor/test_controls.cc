#include "air_controls.h"
#include "test_support.h"

using namespace air;
int main() {
    DebouncedInput debounce;
    CHECK(!debounce.Update(true, 0, true));
    CHECK(!debounce.Update(true, 20, true));
    CHECK(debounce.Update(true, 40, true) == true);
    CHECK(debounce.Update(false, 50, true) == true);
    CHECK(debounce.Update(true, 60, true) == true);
    CHECK(debounce.Update(false, 70, true) == true);
    CHECK(debounce.Update(false, 100, true) == false);
    CHECK(!debounce.Update(false, 120, false));
    CHECK(!debounce.Update(false, 140, true));
    CHECK(debounce.Update(false, 180, true) == false);
    InputPolicy input;
    CHECK(input.Update(ButtonId::Boot, true, 0, true) == ButtonAction::None);
    CHECK(input.Update(ButtonId::Boot, false, 50, true) == ButtonAction::None);
    CHECK(input.Update(ButtonId::Boot, true, 100, true) == ButtonAction::None);
    CHECK(input.Update(ButtonId::Boot, false, 200, true) == ButtonAction::WakeHome);
    input.Update(ButtonId::Power, false, 0, true);
    input.Update(ButtonId::Power, true, 100, true);
    for (int t = 120; t < 3100; t += 20)
        CHECK(input.Update(ButtonId::Power, true, t, true) == ButtonAction::None);
    CHECK(input.Update(ButtonId::Power, true, 3100, true) == ButtonAction::Shutdown);
    CHECK(input.Update(ButtonId::Power, true, 3120, true) == ButtonAction::None);
    CHECK(input.Update(ButtonId::Power, false, 3140, true) == ButtonAction::None);
    input.Update(ButtonId::Power, true, 3200, true);
    CHECK(input.Update(ButtonId::Power, false, 3240, true) == ButtonAction::ToggleDisplay);
    input.Update(ButtonId::Power, true, 3300, true);
    CHECK(input.Update(ButtonId::Power, true, 3401, true) == ButtonAction::None);
    CHECK(input.Update(ButtonId::Power, false, 3420, true) == ButtonAction::None);
    input.Update(ButtonId::Power, true, 3500, true);
    input.Update(ButtonId::Power, false, 3520, false);
    CHECK(input.Update(ButtonId::Power, false, 3540, true) == ButtonAction::None);
    input.Update(ButtonId::Power, true, 3560, true);
    CHECK(input.Update(ButtonId::Power, false, 3580, true) == ButtonAction::ToggleDisplay);
    ActionGate gate;
    auto old = gate.Request(DeviceAction::ConfigureWifi, 0);
    auto current = gate.Request(DeviceAction::Shutdown, 10);
    CHECK(!gate.Confirm(old.id, 20).has_value());
    CHECK(gate.Confirm(current.id, 20) == DeviceAction::Shutdown);
    CHECK(!gate.Confirm(current.id, 21));
    auto expired = gate.Request(DeviceAction::ConfigureWifi, 100);
    CHECK(!gate.Confirm(expired.id, 30100));
    auto cancelled = gate.Request(DeviceAction::Shutdown, 40000);
    gate.Cancel(cancelled.id);
    CHECK(!gate.Confirm(cancelled.id, 40001));
    for (int s = kDeviceStateUnknown; s <= kDeviceStateFatalError; ++s) {
        auto state = static_cast<DeviceState>(s);
        bool expected = state == kDeviceStateIdle || state == kDeviceStateListening ||
                        state == kDeviceStateSpeaking;
        CHECK(CanToggleVoice(state, true, true) == expected);
        CHECK(!CanToggleVoice(state, false, true));
        CHECK(!CanToggleVoice(state, true, false));
    }
    std::puts(
        "controls: release arming, short/long, failed samples, confirmation and voice gate passed");
}
