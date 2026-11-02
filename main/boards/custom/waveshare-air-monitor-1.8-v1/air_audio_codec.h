#pragma once
#include <algorithm>
#include <functional>
#include <utility>
#include "audio/codecs/es8311_audio_codec.h"
#include "settings.h"

namespace air {
// Start and volume changes run on the application task. The observer may only
// publish a mailbox value; it must not call LVGL from the audio/application task.
class AirAudioCodec : public Es8311AudioCodec {
public:
    template <typename... Args>
    explicit AirAudioCodec(std::function<void(int)> observer, Args&&... args)
        : Es8311AudioCodec(std::forward<Args>(args)...), observer_(std::move(observer)) {}

    void Start() override {
        Es8311AudioCodec::Start();
        // The shared startup code replaces zero with ten. Restore the saved AIR
        // value before the device is opened, without writing retained NVS.
        Settings settings("audio", false);
        output_volume_ = std::clamp<int>(settings.GetInt("output_volume", output_volume_), 0, 100);
        PublishVolume();
    }

    void SetOutputVolume(int volume) override {
        Es8311AudioCodec::SetOutputVolume(std::clamp(volume, 0, 100));
        PublishVolume();
    }

private:
    void PublishVolume() {
        if (observer_)
            observer_(output_volume_);
    }
    std::function<void(int)> observer_;
};
}  // namespace air
