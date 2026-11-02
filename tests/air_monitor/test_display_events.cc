#include <cstring>
#include <string>
#include "air_ui_state.h"
#include "test_support.h"
using namespace air;
int main() {
    AirUiState state;
    CHECK(state.page() == Page::Home);
    auto old = state.Notify("连接中", 0, 100);
    auto current = state.Notify("语音离线", 50, 1000);
    state.Expire(old, 101);
    CHECK(std::strcmp(state.notice(), "语音离线") == 0);
    state.Expire(current, 1049);
    CHECK(std::strcmp(state.notice(), "语音离线") == 0);
    state.Expire(current, 1050);
    CHECK(state.notice()[0] == 0);
    std::string long_text;
    for (int i = 0; i < 100; ++i)
        long_text += "正在聆听";
    state.Notify(long_text.c_str(), 2000, 1000);
    CHECK(std::strlen(state.notice()) <= 95);
    CHECK(std::strlen(state.notice()) % 3 == 0);
    state.SetPage(Page::Settings);
    state.SetDrawer(true);
    state.Back();
    CHECK(!state.drawer() && state.page() == Page::Settings);
    state.Back();
    CHECK(state.page() == Page::Home);
    state.SetDisplayOn(false);
    state.SetTheme(true);
    CHECK(!state.display_on() && state.night());
    state.SetDisplayOn(true);
    CHECK(state.night());
    state.SetBrightness(0);
    CHECK(state.brightness() == 1);
    state.SetBrightness(120);
    CHECK(state.brightness() == 100);
    state.SetTheme(false);
    CHECK(state.brightness() == 70);
    state.SetBrightness(80);
    state.SetTheme(true);
    CHECK(state.brightness() == 100);
    state.SetTheme(false);
    CHECK(state.brightness() == 80);
    std::puts(
        "display events: bounded UTF8, notification IDs, drawer, screen and preferences passed");
}
