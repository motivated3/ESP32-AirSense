#pragma once
#include <atomic>
#include "air_hardware.h"
#include "air_sensors.h"
#include "air_solar_theme.h"
#include "air_view.h"
#include "display/lcd_display.h"

namespace air {
class AirDisplay : public SpiLcdDisplay {
public:
    AirDisplay(esp_lcd_panel_io_handle_t io, esp_lcd_panel_handle_t panel, AirSensors& sensors,
               AirHardware& hardware, AirViewCallbacks callbacks);
    ~AirDisplay() override;
    void SetupUI() override;
    void SetStatus(const char*) override {}
    void SetActivationCode(const std::string& code) override;
    void ShowNotification(const char* text, int duration_ms = 3000) override;
    void ShowNotification(const std::string& text, int duration_ms = 3000) override {
        ShowNotification(text.c_str(), duration_ms);
    }
    void SetChatMessage(const char* role, const char* text) override;
    void RemoveChatMessage(const char* role, const char* text) override;
    void ShowVoiceConversation() override {
        requested_on_ = true;
        chat_requested_ = true;
    }
    void ClearChatMessages() override {}
    void SetPreviewImage(std::unique_ptr<LvglImage>) override {}
    bool SetEmotion(const char*) override { return false; }
    void SetTheme(Theme* theme) override;
    void SynchronizeSolar(std::optional<SolarLocation> location, int64_t utc_ms,
                          uint64_t uptime_ms);
    void SetPowerSaveMode(bool) override {}
    // Explicit AirHardware polling owns power; no legacy status-bar side effects.
    void UpdateStatusBar(bool = false) override {}
    void SetHideSubtitle(bool) override {}
    bool SupportsGuiOperations() const override { return false; }
    bool AddTextGlyphs(const std::vector<TextGlyph>&, uint8_t) override { return false; }
    void ClearTextGlyphs() override {}
    bool SetTextFont(std::shared_ptr<LvglFont>) override { return false; }
    void SetEmojiCollection(std::shared_ptr<EmojiCollection>) override {}
    bool SnapshotToJpeg(std::string&, int = 80) override { return false; }
    void WakeHome();
    bool FlushPreferences();
    void ToggleScreen();
    void RequestDeviceAction(DeviceAction action);
    void RequestBrightness(uint8_t percent) { brightness_ = percent; }
    void RequestUserBrightness(uint8_t percent) { user_brightness_ = percent; }
    void RequestVolume(int percent) { volume_ = percent; }
    void SetTouch(lv_indev_t* touch) { touch_ = touch; }
    bool VoiceEnabled() const { return voice_enabled_.load(); }
    int InitialBrightness() const { return initial_brightness_; }
    bool CanSoundAlert(uint32_t generation) const {
        return generation != 0 && generation == alert_sound_token_.load();
    }

private:
    void Tick();
    void SavePreferences();
    bool CommitPreferences(bool force);
    void QueueVolume(int value, std::function<void(int)> apply);
    int DisplayVolume() const;
    void UpdateAlerts(const AirSnapshot& sample, const PowerSnapshot& power);
    void UpdateAutoTheme(uint64_t now_ms);
    AirSensors& sensors_;
    AirHardware& hardware_;
    AirViewCallbacks callbacks_;
    AirUiState state_;
    SolarThemeClock solar_clock_;
    AirAlertPolicy alert_policy_;
    std::unique_ptr<AirView> view_;
    lv_timer_t* timer_ = nullptr;
    lv_indev_t* touch_ = nullptr;
    std::atomic<bool> requested_on_{true}, home_requested_{false}, voice_enabled_{true};
    std::atomic<bool> chat_requested_{false};
    std::atomic<uint8_t> brightness_{70};
    std::atomic<int> user_brightness_{-1};
    std::atomic<int> volume_{-1};
    std::atomic<int> user_volume_{70};
    std::atomic<uint32_t> volume_generation_{0}, applied_volume_generation_{0};
    uint8_t applied_brightness_ = 255;
    int initial_brightness_ = 70;
    uint64_t next_refresh_ = 0;
    uint64_t next_solar_refresh_ = 0;
    uint64_t next_alert_refresh_ = 0;
    uint32_t sounded_alert_generation_ = 0;
    std::atomic<uint32_t> alert_sound_token_{0};
    std::atomic<uint32_t> preferences_generation_{0}, saved_generation_{0};
    std::atomic<bool> save_queued_{false};
    std::array<char, 17> activation_code_{};
};
}  // namespace air
