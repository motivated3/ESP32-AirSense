#include "air_ui_state.h"
#include <algorithm>
#include <cstring>
namespace air {
uint64_t AirUiState::Notify(const char* text, uint64_t now_ms, int duration_ms) {
    const size_t length = text ? std::strlen(text) : 0;
    size_t count = std::min(length, notice_.size() - 1);
    if (count < length) {
        while (count && (static_cast<unsigned char>(text[count]) & 0xC0) == 0x80)
            --count;
    }
    if (count)
        std::memcpy(notice_.data(), text, count);
    notice_[count] = 0;
    notice_until_ = now_ms + std::clamp(duration_ms, 0, 30000);
    return ++notice_id_;
}
void AirUiState::Expire(uint64_t id, uint64_t now_ms) {
    if (id == notice_id_ && now_ms >= notice_until_)
        notice_[0] = 0;
}
void AirUiState::Back() {
    if (drawer_)
        drawer_ = false;
    else
        page_ = Page::Home;
}
void AirUiState::SetBrightness(int value) {
    (night_ ? night_brightness_ : day_brightness_) = std::clamp(value, 1, 100);
}
}  // namespace air
