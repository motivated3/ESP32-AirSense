#include "air_alert_sound.h"

#include <array>
#include <cstring>
#include <memory>

#include "air_alert_tone.h"
#include "audio_service.h"
#include "ogg_demuxer.h"

namespace air {

bool TryPlayAirAlertTone(AudioService& audio) {
    if (!audio.IsPlaybackIdle()) {
        return false;
    }

    // Keep the demuxer's 2 KB packet buffer off the application task's stack.
    auto demuxer = std::make_unique<OggDemuxer>();
    std::array<std::unique_ptr<AudioStreamPacket>, 5> packets;
    size_t count = 0;
    bool valid = true;
    demuxer->OnPacket([&](const uint8_t* data, int rate, int duration, size_t size) {
        if (!valid) {
            return;
        }
        if (count == packets.size() || rate != 16000 || duration != 60 || size == 0) {
            valid = false;
            return;
        }
        auto packet = std::make_unique<AudioStreamPacket>();
        packet->sample_rate = rate;
        packet->frame_duration = duration;
        packet->payload.resize(size);
        std::memcpy(packet->payload.data(), data, size);
        packets[count++] = std::move(packet);
    });
    const size_t consumed = demuxer->Process(kAlertToneOgg, sizeof(kAlertToneOgg));
    if (!valid || count == 0 || consumed != sizeof(kAlertToneOgg) || !demuxer->Finish() ||
        !audio.IsPlaybackIdle()) {
        return false;
    }

    for (size_t i = 0; i < count; ++i) {
        if (!audio.PushPacketToDecodeQueue(std::move(packets[i]), false)) {
            return false;
        }
    }
    return true;
}

}  // namespace air
