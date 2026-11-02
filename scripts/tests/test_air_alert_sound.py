"""Run the AIR cue through the real Ogg parser and a bounded audio queue."""

import os
import shlex
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
AIR = ROOT / "main/boards/custom/waveshare-air-monitor-1.8-v1"
DEMUXER = ROOT / "main/audio/demuxer"


class AirAlertSoundTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shlex.split(os.environ.get("CXX", "c++"))
        if not compiler or shutil.which(compiler[0]) is None:
            raise unittest.SkipTest("requires a host C++20 compiler")
        assert (AIR / "air_alert_sound.cc").is_file(), "AIR alert sound helper is missing"
        cls.directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.directory.cleanup)
        path = Path(cls.directory.name)
        (path / "esp_log.h").write_text(
            "#define ESP_LOGE(...) ((void)0)\n"
            "#define ESP_LOGW(...) ((void)0)\n"
            "#define ESP_LOGD(...) ((void)0)\n", encoding="utf-8")
        (path / "audio_service.h").write_text(textwrap.dedent(r'''
            #pragma once
            #include <cassert>
            #include <cstdint>
            #include <memory>
            #include <string_view>
            #include <vector>
            struct AudioStreamPacket {
                int sample_rate = 0, frame_duration = 0;
                uint32_t timestamp = 0, playback_id = 0, media_position_ms = 0;
                std::vector<uint8_t> payload;
            };
            class AudioService {
            public:
                bool idle = true;
                int volume = 47, accepted_limit = 5, attempts = 0, idle_checks = 0;
                std::vector<AudioStreamPacket> accepted;
                bool IsPlaybackIdle() { ++idle_checks; return idle; }
                bool PushPacketToDecodeQueue(std::unique_ptr<AudioStreamPacket> packet,
                                             bool wait = false) {
                    assert(!wait && "a full audio queue must never wait");
                    ++attempts;
                    assert(packet);
                    if (static_cast<int>(accepted.size()) >= accepted_limit) return false;
                    accepted.push_back(*packet);
                    return true;
                }
                void PlaySound(const std::string_view&) = delete;
                void ResetDecoder() = delete;
                void SetOutputVolume(int) = delete;
                void EnableOutput(bool) = delete;
            };
        '''), encoding="utf-8")
        driver = path / "driver.cc"
        driver.write_text(textwrap.dedent(r'''
            #include <cassert>
            #include <string>
            #include "air_alert_sound.h"
            #include "air_alert_tone.h"
            #include "audio_service.h"
            #include "ogg_demuxer.h"
            int main(int argc, char** argv) {
                assert(argc == 2);
                const std::string scenario = argv[1];
                AudioService audio;
                if (scenario == "healthy") {
                    OggDemuxer demuxer;
                    std::vector<AudioStreamPacket> original;
                    demuxer.OnPacket([&](const uint8_t* data, int rate, int duration, size_t size) {
                        assert(rate == 16000 && duration == 60 && size > 0);
                        AudioStreamPacket packet;
                        packet.sample_rate = rate;
                        packet.frame_duration = duration;
                        packet.payload.assign(data, data + size);
                        original.push_back(std::move(packet));
                    });
                    assert(demuxer.Process(air::kAlertToneOgg, sizeof(air::kAlertToneOgg)) ==
                           sizeof(air::kAlertToneOgg));
                    // Finish requires valid OpusHead, tags, mono, complete pages and audio.
                    assert(demuxer.Finish() && !demuxer.HasError());
                    assert(original.size() >= 1 && original.size() <= 5);
                    int duration = 0;
                    for (const auto& packet : original) duration += packet.frame_duration;
                    assert(duration >= 240 && duration <= 360);
                    assert(air::TryPlayAirAlertTone(audio));
                    assert(audio.accepted.size() == original.size());
                    assert(audio.attempts == static_cast<int>(original.size()));
                    for (size_t i = 0; i < original.size(); ++i) {
                        assert(audio.accepted[i].sample_rate == original[i].sample_rate);
                        assert(audio.accepted[i].frame_duration == original[i].frame_duration);
                        assert(audio.accepted[i].payload == original[i].payload);
                        assert(audio.accepted[i].timestamp == 0 && audio.accepted[i].playback_id == 0);
                    }
                } else if (scenario == "busy") {
                    audio.idle = false;
                    assert(!air::TryPlayAirAlertTone(audio));
                    assert(audio.attempts == 0 && audio.accepted.empty());
                } else if (scenario == "full") {
                    audio.accepted_limit = 0;
                    assert(!air::TryPlayAirAlertTone(audio));
                    assert(audio.attempts == 1 && audio.accepted.empty());
                } else {
                    assert(scenario == "partial");
                    audio.accepted_limit = 2;
                    assert(!air::TryPlayAirAlertTone(audio));
                    assert(audio.attempts == 3 && audio.accepted.size() == 2);
                    // There are no delayed jobs or retries owned by this helper.
                }
                assert(audio.idle_checks >= 1 && audio.volume == 47);
            }
        '''), encoding="utf-8")
        cls.executable = path / "air_alert_sound_test"
        result = subprocess.run(compiler + ["-std=c++20", "-Wall", "-Wextra", "-Werror",
                                f"-I{path}", f"-I{AIR}", f"-I{DEMUXER}", str(driver),
                                str(AIR / "air_alert_sound.cc"), str(DEMUXER / "ogg_demuxer.cc"),
                                "-o", str(cls.executable)], capture_output=True, text=True)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)

    def check_scenario(self, name):
        result = subprocess.run([self.executable, name], capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_valid_mono_cue_uses_original_frames_and_bounded_duration(self):
        self.check_scenario("healthy")

    def test_existing_playback_skips_cue_without_queue_writes(self):
        self.check_scenario("busy")

    def test_full_queue_is_attempted_once_without_waiting(self):
        self.check_scenario("full")

    def test_partial_queue_failure_stops_immediately(self):
        self.check_scenario("partial")


if __name__ == "__main__":
    unittest.main()
