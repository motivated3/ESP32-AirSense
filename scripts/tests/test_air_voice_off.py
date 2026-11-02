"""Run application notification and incoming voice callbacks with voice disabled."""

import os
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


class AirVoiceOffTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shlex.split(os.environ.get("CXX", "c++"))
        if not compiler or shutil.which(compiler[0]) is None:
            raise unittest.SkipTest("requires a host C++23 compiler")
        source = (ROOT / "main/application.cc").read_text()
        initialize = definition(source, "void Application::InitializeProtocol()")
        # Keep the complete production registration expressions and their lambdas;
        # only transport construction and unrelated initialization are omitted.
        callbacks = "void Application::InitializeProtocol() {\n"
        callbacks += "auto display = Board::GetInstance().GetDisplay();\n"
        for registration in ("OnIncomingAudio", "OnIncomingJson"):
            callbacks += definition(initialize, f"protocol_->{registration}(") + ");\n"
        callbacks += "}\n"
        notification = definition(source, "void Application::StartNotification(")
        platform = r'''
            #include <atomic>
            #include <cassert>
            #include <cstdint>
            #include <cstring>
            #include <functional>
            #include <limits>
            #include <map>
            #include <memory>
            #include <optional>
            #include <string>
            #include <string_view>
            #include <utility>
            #include <vector>
            #include "device_state.h"
            #define TAG "HostVoiceOff"
            #define ESP_LOGI(...) ((void)0)
            #define ESP_LOGW(...) ((void)0)
            #define ESP_LOGE(...) ((void)0)

            struct cJSON {
                enum Kind { Object, String, Array, Number } kind;
                const char* valuestring = nullptr;
                double valuedouble = 0;
                cJSON *child = nullptr, *next = nullptr;
                std::map<std::string, cJSON*> members;
                cJSON(Kind kind, const char* value = nullptr) : kind(kind), valuestring(value) {}
            };
            cJSON* cJSON_GetObjectItem(const cJSON* node, const char* key) {
                if (!node) return nullptr;
                auto item = node->members.find(key);
                return item == node->members.end() ? nullptr : item->second;
            }
            bool cJSON_IsString(const cJSON* node) { return node && node->kind == cJSON::String; }
            bool cJSON_IsArray(const cJSON* node) { return node && node->kind == cJSON::Array; }
            bool cJSON_IsNumber(const cJSON* node) { return node && node->kind == cJSON::Number; }
            bool cJSON_IsObject(const cJSON* node) { return node && node->kind == cJSON::Object; }
            #define cJSON_ArrayForEach(item, array) \
                for (item = (array)->child; item; item = item->next)
            struct TextGlyph {};
            struct TextGlyphPayload {
                static bool Parse(const cJSON*, std::vector<TextGlyph>&, uint8_t&) { return true; }
            };
            struct McpServer {
                static McpServer& GetInstance() { static McpServer server; return server; }
                void ParseMessage(const cJSON*) {}
            };
            namespace Lang::Sounds {
                constexpr std::string_view OGG_POPUP = "popup", OGG_VIBRATION = "vibration";
            }
            enum class PowerSaveLevel { PERFORMANCE, LOW_POWER };
            enum ListeningMode { kListeningModeManualStop, kListeningModeAutoStop };
            struct AudioStreamPacket {};
            struct NotifySubtitle { uint32_t start_ms; std::string text; };
            struct Display {
                void SetChatMessage(const char*, const char*) {}
                void AddTextGlyphs(const std::vector<TextGlyph>&, uint8_t) {}
                void SetEmotion(const char*) {}
            };
            struct Board {
                bool voice_enabled = true;
                int power_changes = 0;
                Display display;
                static Board& GetInstance() { static Board board; return board; }
                bool IsVoiceEnabled() const { return voice_enabled; }
                Display* GetDisplay() { return &display; }
                void SetPowerSaveLevel(PowerSaveLevel) { ++power_changes; }
            };
            struct AudioService {
                int changes = 0, decoded_packets = 0;
                void EnableVoiceProcessing(bool) { ++changes; }
                void EnableWakeWordDetection(bool) { ++changes; }
                bool IsAfeWakeWord() const { return false; }
                void ReleaseWakeWordResources() { ++changes; }
                bool PopPacketFromSendQueue() { return false; }
                void ResetDecoder() { ++changes; }
                void PlaySound(std::string_view) { ++changes; }
                uint32_t PlaybackGeneration() { return 0; }
                void PushPacketToDecodeQueue(std::unique_ptr<AudioStreamPacket>, bool = false,
                                             std::optional<uint32_t> = std::nullopt) { ++decoded_packets; }
            };
            struct NotifyPlayer {
                int starts = 0;
                std::string last_url;
                bool IsBusy() const { return false; }
                bool Start(std::string url, std::vector<NotifySubtitle>, uint32_t,
                           std::function<void(uint32_t, const std::string&)>,
                           std::function<void(uint32_t, bool)>) {
                    ++starts;
                    last_url = std::move(url);
                    return true;
                }
            };
            struct Protocol {
                std::function<void(std::unique_ptr<AudioStreamPacket>)> audio;
                std::function<void(const cJSON*)> json;
                void OnIncomingAudio(decltype(audio) callback) { audio = std::move(callback); }
                void OnIncomingJson(decltype(json) callback) { json = std::move(callback); }
                const std::string& session_id() const { static const std::string id; return id; }
            };
            class Application {
            public:
                DeviceState state = kDeviceStateIdle;
                int state_changes = 0;
                bool aborted_ = true;
                bool voice_session_cancelled_ = false;
                std::atomic<uint32_t> voice_session_generation_{0};
                ListeningMode listening_mode_ = kListeningModeAutoStop;
                uint32_t notification_playback_id_ = 0;
                AudioService audio_service_;
                NotifyPlayer notify_player_;
                std::unique_ptr<Protocol> protocol_ = std::make_unique<Protocol>();
                std::vector<std::function<void()>> queued;
                DeviceState GetDeviceState() const { return state; }
                bool SetDeviceState(DeviceState next) { ++state_changes; state = next; return true; }
                void Schedule(std::function<void()>&& callback) { queued.push_back(std::move(callback)); }
                void Drain() {
                    auto tasks = std::move(queued);
                    queued.clear();
                    for (auto& task : tasks) task();
                }
                void InitializeProtocol();
                void StartNotification(std::string, std::vector<NotifySubtitle>);
                void StopNotification() {}
                void HandleNotificationFinished(uint32_t, bool) {}
                void Reboot() {}
                void Alert(const char*, const char*, const char*, std::string_view) {}
            };
        '''
        checks = r'''
            int main(int argc, char** argv) {
                assert(argc == 2);
                std::string scenario = argv[1];
                auto& board = Board::GetInstance();
                Application app;
                app.InitializeProtocol();
                if (scenario == "notification-disabled" || scenario == "notification-enabled") {
                    board.voice_enabled = scenario == "notification-enabled";
                    app.StartNotification("https://example.invalid/notification.opus", {});
                    if (board.voice_enabled) {
                        assert(app.notify_player_.starts == 1);
                        assert(app.notify_player_.last_url == "https://example.invalid/notification.opus");
                        assert(app.state == kDeviceStateNotifying);
                    } else {
                        assert(app.notify_player_.starts == 0 && "voice-off must not start a notification download");
                        assert(app.state_changes == 0 && app.state == kDeviceStateIdle);
                        assert(app.audio_service_.changes == 0 && board.power_changes == 0);
                    }
                } else if (scenario == "audio-disabled" || scenario == "audio-enabled") {
                    app.state = kDeviceStateSpeaking;
                    board.voice_enabled = scenario == "audio-enabled";
                    app.protocol_->audio(std::make_unique<AudioStreamPacket>());
                    assert(app.audio_service_.decoded_packets == (board.voice_enabled ? 1 : 0) &&
                           "voice-off must discard late incoming audio");
                } else {
                    assert(scenario == "tts-disabled" || scenario == "tts-queued-disabled" ||
                           scenario == "tts-enabled");
                    cJSON type(cJSON::String, "tts"), state(cJSON::String, "start"), root(cJSON::Object);
                    root.members = {{"type", &type}, {"state", &state}};
                    board.voice_enabled = scenario != "tts-disabled";
                    app.protocol_->json(&root);
                    assert(app.state == kDeviceStateIdle);
                    if (scenario == "tts-queued-disabled") {
                        assert(app.queued.size() == 1 && "the event must have been accepted before voice-off");
                        board.voice_enabled = false;
                    }
                    app.Drain();
                    if (scenario == "tts-enabled") {
                        assert(app.state == kDeviceStateSpeaking && !app.aborted_);
                    } else {
                        assert(app.state == kDeviceStateIdle && "voice-off must reject incoming or already queued TTS");
                        assert(app.state_changes == 0 && app.aborted_);
                    }
                }
            }
        '''
        cls.directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.directory.cleanup)
        path = Path(cls.directory.name)
        driver = path / "air_voice_off.cc"
        driver.write_text(textwrap.dedent(platform) + notification + callbacks + textwrap.dedent(checks))
        cls.executable = path / "air_voice_off"
        compiled = subprocess.run(
            compiler + ["-std=c++23", "-I", str(ROOT / "main"), str(driver), "-o", str(cls.executable)],
            capture_output=True, text=True,
        )
        if compiled.returncode:
            raise AssertionError(compiled.stdout + compiled.stderr)

    def run_scenario(self, scenario):
        result = subprocess.run([str(self.executable), scenario], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_voice_off_blocks_notification_before_any_side_effect(self):
        self.run_scenario("notification-disabled")

    def test_voice_on_keeps_notification_playback(self):
        self.run_scenario("notification-enabled")

    def test_voice_off_blocks_incoming_tts(self):
        self.run_scenario("tts-disabled")

    def test_voice_off_rejects_tts_queued_before_it_was_disabled(self):
        self.run_scenario("tts-queued-disabled")

    def test_voice_on_keeps_tts_start(self):
        self.run_scenario("tts-enabled")

    def test_voice_off_discards_late_incoming_audio(self):
        self.run_scenario("audio-disabled")

    def test_voice_on_keeps_incoming_audio(self):
        self.run_scenario("audio-enabled")
