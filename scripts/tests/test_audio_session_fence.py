"""Exercise the actual audio queue methods and codec worker across session cancellation."""

import os
import re
import shlex
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def definition(source, signature):
    start = source.index(signature)
    brace = source.index("{", start)
    depth, end = 1, brace + 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end]


class AudioSessionFenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shlex.split(os.environ.get("CXX", "c++"))
        if not compiler or shutil.which(compiler[0]) is None:
            raise unittest.SkipTest("requires a host C++23 compiler")
        source = (ROOT / "main/audio/audio_service.cc").read_text()
        header = (ROOT / "main/audio/audio_service.h").read_text()
        header = re.sub(r"^#include .*$", "", header, flags=re.MULTILINE)
        header = header.replace("private:", "public:")
        # Observe when the real worker/waiting producer blocks, without timing sleeps.
        header = header.replace("std::condition_variable audio_queue_cv_", "ProbeConditionVariable audio_queue_cv_")
        # A scheduler gate stops the producer immediately before taking this lock.
        header = header.replace("std::mutex audio_queue_mutex_", "ProducerGateMutex audio_queue_mutex_")
        methods = "\n".join(definition(source, signature) for signature in (
            "AudioService::AudioService()",
            "AudioService::~AudioService()",
            "void AudioService::OpusCodecTask()",
            "void AudioService::PushTaskToEncodeQueue(",
            "bool AudioService::PushPacketToDecodeQueue(",
            "std::unique_ptr<AudioStreamPacket> AudioService::PopPacketFromSendQueue()",
            "void AudioService::ResetDecoder()",
            "void AudioService::DiscardRecordedAudio()",
            "uint32_t AudioService::PlaybackGeneration()",
            "bool AudioService::IsPlaybackDrainedLocked() const",
            "bool AudioService::MarkPlaybackDrainedLocked()",
        ))
        output_callback = definition(source, "audio_engine_->OnOutput(")
        methods += "\nvoid AudioService::Initialize(AudioCodec*) {\n"
        methods += "audio_engine_ = std::make_unique<AudioEngine>();\n" + output_callback + ");\n}\n"
        methods = re.sub(r"std::(unique_lock|lock_guard)<std::mutex> (\w+)\(audio_queue_mutex_\)",
                         r"std::\1<ProducerGateMutex> \2(audio_queue_mutex_)", methods)
        packet = definition((ROOT / "main/protocols/protocol.h").read_text(), "struct AudioStreamPacket") + ";\n"
        platform = r"""
            #include <atomic>
            #include <cassert>
            #include <chrono>
            #include <condition_variable>
            #include <cstdint>
            #include <cstdlib>
            #include <functional>
            #include <memory>
            #include <mutex>
            #include <optional>
            #include <string>
            #include <string_view>
            #include <thread>
            #include <vector>
            #include "fixed_queue.h"
            using namespace std::chrono_literals;
            #define ESP_LOGE(...) ((void)0)
            #define ESP_LOGW(...) ((void)0)
            #define TAG "HostAudioSessionFence"
            constexpr int ESP_AUDIO_ERR_OK = 0, ESP_AUDIO_DEC_RECOVERY_NONE = 0;
            struct srmodel_list_t {};
            struct AudioEngine {
                std::function<void(std::vector<int16_t>&&)> output;
                void OnOutput(decltype(output) callback) { output = std::move(callback); }
            };
            struct AudioDebugger {};
            struct AudioCodec { int output_sample_rate() const { return 16000; } };
            using esp_timer_handle_t = void*;
            using esp_ae_rate_cvt_handle_t = void*;
            using esp_ae_sample_t = void*;
            using TaskHandle_t = void*;
            using EventGroupHandle_t = std::atomic<uint32_t>*;
            EventGroupHandle_t xEventGroupCreate() { return new std::atomic<uint32_t>(1 << 2); }
            uint32_t xEventGroupGetBits(EventGroupHandle_t group) { return group->load(); }
            void vEventGroupDelete(EventGroupHandle_t group) { delete group; }
            int64_t esp_timer_get_time() { return 0; }
            void esp_opus_enc_close(void*) {}
            void esp_opus_dec_close(void*) {}
            void esp_ae_rate_cvt_close(void*) {}
            void esp_opus_dec_reset(void*) {}
            struct esp_audio_dec_in_raw_t { uint8_t* buffer; uint32_t len, consumed; int frame_recover; };
            struct esp_audio_dec_out_frame_t { uint8_t* buffer; uint32_t len, decoded_size; };
            struct esp_audio_dec_info_t {};
            int esp_opus_dec_decode(void*, esp_audio_dec_in_raw_t*, esp_audio_dec_out_frame_t*, esp_audio_dec_info_t*) { return -1; }
            void esp_ae_rate_cvt_get_max_out_sample_num(void*, size_t size, uint32_t* out) { *out = size; }
            void esp_ae_rate_cvt_process(void*, esp_ae_sample_t, size_t, esp_ae_sample_t, uint32_t*) {}
            struct esp_audio_enc_in_frame_t { uint8_t* buffer; uint32_t len; };
            struct esp_audio_enc_out_frame_t { uint8_t* buffer; uint32_t len, encoded_bytes; };
            struct Probe {
                std::mutex mutex;
                std::condition_variable changed;
                bool encoder_entered = false, release_encoder = false, pause_encoder = false;
                bool producer_entered = false, release_producer = false;
                int waits = 0;
                void WaitFor(std::function<bool()> ready) {
                    std::unique_lock<std::mutex> lock(mutex);
                    assert(changed.wait_for(lock, 3s, ready) && "test rendezvous timed out");
                }
            } probe;
            thread_local bool gate_next_queue_lock = false;
            struct ProducerGateMutex {
                std::mutex mutex;
                void lock() {
                    if (gate_next_queue_lock) {
                        gate_next_queue_lock = false;
                        std::unique_lock<std::mutex> guard(probe.mutex);
                        probe.producer_entered = true;
                        probe.changed.notify_all();
                        assert(probe.changed.wait_for(guard, 3s, [] { return probe.release_producer; }));
                    }
                    mutex.lock();
                }
                void unlock() { mutex.unlock(); }
            };
            struct ProbeConditionVariable {
                std::condition_variable_any cv;
                template<class Mutex, class Predicate> void wait(std::unique_lock<Mutex>& lock, Predicate ready) {
                    if (!ready()) {
                        std::lock_guard<std::mutex> guard(probe.mutex);
                        ++probe.waits;
                        probe.changed.notify_all();
                    }
                    cv.wait(lock, ready);
                }
                void notify_all() { cv.notify_all(); }
            };
            int esp_opus_enc_process(void*, esp_audio_enc_in_frame_t* in, esp_audio_enc_out_frame_t* out) {
                std::unique_lock<std::mutex> lock(probe.mutex);
                probe.encoder_entered = true;
                probe.changed.notify_all();
                if (probe.pause_encoder) {
                    assert(probe.changed.wait_for(lock, 3s, [] { return probe.release_encoder; }));
                }
                out->buffer[0] = in->buffer[0];
                out->encoded_bytes = 1;
                return ESP_AUDIO_ERR_OK;
            }
        """
        checks = r"""
            void AudioService::SetDecodeSampleRate(int, int) {}
            auto Packet(uint8_t value = 7) {
                auto packet = std::make_unique<AudioStreamPacket>();
                packet->payload = {value};
                return packet;
            }
            void StopWorker(AudioService& service, std::thread& worker) {
                { std::lock_guard lock(service.audio_queue_mutex_); service.service_stopped_ = true; }
                service.audio_queue_cv_.notify_all();
                worker.join();
            }
            int main(int argc, char** argv) {
                assert(argc == 2);
                const std::string scenario = argv[1];
                AudioService service;
                service.service_stopped_ = false;
                service.encoder_frame_size_ = 2;
                service.encoder_outbuf_size_ = 8;
                service.opus_encoder_ = reinterpret_cast<void*>(1);
                std::atomic<int> sends = 0;
                service.callbacks_.on_send_queue_available = [&] { ++sends; };
                if (scenario == "stale-producer") {
                    service.Initialize(nullptr);
                    std::thread producer([&] {
                        gate_next_queue_lock = true;
                        service.audio_engine_->output({41, 42});
                    });
                    probe.WaitFor([] { return probe.producer_entered; });
                    service.voice_enabled_ = false;
                    service.event_group_->store(0);
                    service.DiscardRecordedAudio();
                    service.voice_enabled_ = true;
                    service.event_group_->store(AS_EVENT_AUDIO_PROCESSOR_RUNNING);
                    service.timestamp_queue_.push_back(777);
                    { std::lock_guard<std::mutex> lock(probe.mutex); probe.release_producer = true; }
                    probe.changed.notify_all();
                    producer.join();
                    assert(service.audio_encode_queue_.empty() && "old engine producer must not acquire a fresh session generation after reenable");
                    assert(service.timestamp_queue_.size() == 1 && "rejected old producer must preserve the new session timestamp");
                    service.audio_engine_->output({51, 52});
                    std::thread worker([&] { service.OpusCodecTask(); });
                    probe.WaitFor([] { return probe.waits >= 1; });
                    StopWorker(service, worker);
                    auto packet = service.PopPacketFromSendQueue();
                    assert(packet && packet->payload == std::vector<uint8_t>{51} && packet->timestamp == 777 && sends == 1);
                } else if (scenario == "in-flight-send" || scenario == "in-flight-testing") {
                    const bool testing = scenario == "in-flight-testing";
                    probe.pause_encoder = true;
                    service.PushTaskToEncodeQueue(testing ? kAudioTaskTypeEncodeToTestingQueue : kAudioTaskTypeEncodeToSendQueue, {11, 12});
                    std::thread worker([&] { service.OpusCodecTask(); });
                    probe.WaitFor([] { return probe.encoder_entered; });
                    service.DiscardRecordedAudio();
                    // Re-enabling the next session must not revive the popped frame.
                    service.voice_enabled_ = false;
                    service.event_group_->store(0);
                    service.voice_enabled_ = true;
                    service.event_group_->store(AS_EVENT_AUDIO_PROCESSOR_RUNNING);
                    { std::lock_guard<std::mutex> lock(probe.mutex); probe.release_encoder = true; }
                    probe.changed.notify_all();
                    probe.WaitFor([] { return probe.waits >= 1; });
                    StopWorker(service, worker);
                    assert(!service.PopPacketFromSendQueue() && "cancelled in-flight PCM must not reappear in send queue");
                    assert(sends == 0 && "cancelled send must not fire send-available callback");
                    assert(service.audio_testing_queue_.size() == (testing ? 1 : 0) && "testing encode must survive cancellation of recorded speech");
                } else if (scenario == "fresh-send" || scenario == "testing-voice-off") {
                    const bool testing = scenario == "testing-voice-off";
                    service.DiscardRecordedAudio();
                    if (testing) { service.voice_enabled_ = false; service.event_group_->store(0); }
                    service.PushTaskToEncodeQueue(testing ? kAudioTaskTypeEncodeToTestingQueue : kAudioTaskTypeEncodeToSendQueue, {23, 24});
                    std::thread worker([&] { service.OpusCodecTask(); });
                    probe.WaitFor([] { return probe.waits >= 1; });
                    StopWorker(service, worker);
                    if (testing) {
                        assert(service.audio_testing_queue_.size() == 1 && sends == 0);
                    } else {
                        auto packet = service.PopPacketFromSendQueue();
                        assert(packet && packet->payload == std::vector<uint8_t>{23} && sends == 1);
                    }
                } else if (scenario == "late-processor-output" || scenario == "late-voice-off-output") {
                    service.timestamp_queue_.push_back(123);
                    if (scenario == "late-processor-output") service.event_group_->store(0);
                    else service.voice_enabled_ = false;
                    service.PushTaskToEncodeQueue(kAudioTaskTypeEncodeToSendQueue, {31, 32});
                    assert(service.audio_encode_queue_.empty() && "disabled processing must reject late engine output");
                    assert(service.timestamp_queue_.size() == 1 && "rejected PCM must not consume AEC timestamp");
                } else if (scenario == "discard-queued") {
                    service.PushTaskToEncodeQueue(kAudioTaskTypeEncodeToSendQueue, {11, 12});
                    service.audio_send_queue_.push_back(Packet());
                    service.timestamp_queue_.push_back(123);
                    service.audio_testing_queue_.push_back(Packet(9));
                    service.audio_decode_queue_.push_back(Packet(8));
                    AudioTask playback; playback.type = kAudioTaskTypeDecodeToPlaybackQueue; playback.pcm = {1, 2};
                    service.audio_playback_queue_.push_back(std::move(playback));
                    const auto generation = service.PlaybackGeneration();
                    service.DiscardRecordedAudio();
                    assert(service.audio_encode_queue_.empty() && service.audio_send_queue_.empty() && service.timestamp_queue_.empty());
                    assert(service.audio_testing_queue_.size() == 1 && service.audio_decode_queue_.size() == 1 && service.audio_playback_queue_.size() == 1);
                    assert(service.PlaybackGeneration() == generation && "recording discard must not cancel playback");
                } else if (scenario == "stale-receiver" || scenario == "current-receiver") {
                    const auto old_generation = service.PlaybackGeneration();
                    service.ResetDecoder();
                    const auto current = service.PlaybackGeneration();
                    const bool accepted = service.PushPacketToDecodeQueue(Packet(), false, scenario == "stale-receiver" ? old_generation : current);
                    assert(accepted == (scenario == "current-receiver") && "receiver token must be checked even when queue has space");
                    assert(service.audio_decode_queue_.size() == (accepted ? 1 : 0));
                } else if (scenario == "waiting-reset") {
                    const auto generation = service.PlaybackGeneration();
                    for (int i = 0; i < MAX_DECODE_PACKETS_IN_QUEUE; ++i) assert(service.PushPacketToDecodeQueue(Packet()));
                    bool accepted = true;
                    std::thread receiver([&] { accepted = service.PushPacketToDecodeQueue(Packet(), true, generation); });
                    probe.WaitFor([] { return probe.waits >= 1; });
                    service.ResetDecoder();
                    receiver.join();
                    assert(!accepted && service.audio_decode_queue_.empty() && "reset must reject an already waiting receiver");
                } else {
                    assert(scenario == "legacy-receiver");
                    assert(service.PushPacketToDecodeQueue(Packet()) && "ordinary callers retain the default token contract");
                }
            }
        """
        cls.directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.directory.cleanup)
        path = Path(cls.directory.name)
        (path / "esp_system.h").write_text('#pragma once\n#include <cstdlib>\ninline void esp_system_abort(const char*) { std::abort(); }\n')
        driver = path / "audio_session_fence.cc"
        driver.write_text(textwrap.dedent(platform) + packet + header + methods + textwrap.dedent(checks))
        cls.executable = path / "audio_session_fence"
        result = subprocess.run(compiler + ["-std=c++23", "-pthread", "-Wall", "-Wextra", "-Werror", "-Wno-sign-compare",
                                           "-I", str(path), "-I", str(ROOT / "main/audio"), str(driver), "-o", str(cls.executable)],
                                capture_output=True, text=True)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)

    def run_scenario(self, scenario):
        result = subprocess.run([str(self.executable), scenario], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_old_engine_producer_cannot_join_a_reenabled_session(self):
        self.run_scenario("stale-producer")

    def test_discard_rejects_pcm_already_inside_encoder_after_reenable(self):
        self.run_scenario("in-flight-send")

    def test_fresh_session_still_sends_audio(self):
        self.run_scenario("fresh-send")

    def test_discard_does_not_cancel_in_flight_testing_encode(self):
        self.run_scenario("in-flight-testing")

    def test_testing_encode_still_works_with_voice_disabled(self):
        self.run_scenario("testing-voice-off")

    def test_late_engine_output_is_rejected_when_processor_is_stopped(self):
        self.run_scenario("late-processor-output")

    def test_late_engine_output_is_rejected_when_voice_is_disabled(self):
        self.run_scenario("late-voice-off-output")

    def test_discard_clears_recorded_queues_and_preserves_playback_and_testing(self):
        self.run_scenario("discard-queued")

    def test_receiver_token_captured_before_reset_is_rejected_with_free_space(self):
        self.run_scenario("stale-receiver")

    def test_receiver_using_current_token_is_accepted(self):
        self.run_scenario("current-receiver")

    def test_reset_rejects_waiting_receiver_and_wakes_it(self):
        self.run_scenario("waiting-reset")

    def test_existing_receiver_calls_keep_their_default_behavior(self):
        self.run_scenario("legacy-receiver")
