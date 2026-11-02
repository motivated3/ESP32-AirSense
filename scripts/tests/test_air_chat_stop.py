"""Run the real session-stop method and registered voice callbacks on the host."""

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


class AirChatStopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shlex.split(os.environ.get("CXX", "c++"))
        if not compiler or shutil.which(compiler[0]) is None:
            raise unittest.SkipTest("requires a host C++23 compiler")
        source = (ROOT / "main/application.cc").read_text()
        methods = "\n".join(definition(source, signature) for signature in (
            "void Application::EndVoiceSession()",
            "void Application::SetVoiceEnabled(bool enabled)",
            "void Application::AbortSpeaking(",
            "void Application::ContinueOpenAudioChannel(",
            "void Application::ContinueWakeWordInvoke(",
            "void Application::BeginWakeWordInvoke(",
            "void Application::HandleWakeWordDetectedEvent()",
            "void Application::HandleToggleChatEvent()",
            "void Application::HandleStartListeningEvent()",
            "void Application::HandleStateChangedEvent()",
            "void Application::SetListeningMode(",
            "ListeningMode Application::GetDefaultListeningMode() const",
        ))
        initialize = definition(source, "void Application::InitializeProtocol()")
        callbacks = "void Application::InitializeProtocol() {\n"
        callbacks += "auto& board = Board::GetInstance();\nauto display = board.GetDisplay();\n"
        for registration in ("OnIncomingAudio", "OnAudioChannelClosed", "OnIncomingJson"):
            callbacks += definition(initialize, f"protocol_->{registration}(") + ");\n"
        callbacks += "}\n"
        platform = r'''
            #include <atomic>
            #include <cassert>
            #include <cstdint>
            #include <cstring>
            #include <deque>
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
            #define TAG "HostChatStop"
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
            bool cJSON_IsString(const cJSON* n) { return n && n->kind == cJSON::String; }
            bool cJSON_IsArray(const cJSON* n) { return n && n->kind == cJSON::Array; }
            bool cJSON_IsNumber(const cJSON* n) { return n && n->kind == cJSON::Number; }
            bool cJSON_IsObject(const cJSON* n) { return n && n->kind == cJSON::Object; }
            #define cJSON_ArrayForEach(item, array) \
                for (item = (array)->child; item; item = item->next)
            struct TextGlyph {};
            struct TextGlyphPayload {
                static bool Parse(const cJSON*, std::vector<TextGlyph>&, uint8_t&) { return true; }
            };
            struct McpServer {
                static McpServer& GetInstance() { static McpServer s; return s; }
                void ParseMessage(const cJSON*) {}
            };
            namespace Lang::Sounds {
                constexpr std::string_view OGG_VIBRATION = "vibration", OGG_POPUP = "popup";
            }
            namespace Lang::Strings {
                constexpr const char *STANDBY = "idle", *CONNECTING = "connecting",
                                     *LISTENING = "listening", *SPEAKING = "speaking";
            }
            enum class PowerSaveLevel { PERFORMANCE, LOW_POWER };
            enum ListeningMode {
                kListeningModeManualStop, kListeningModeAutoStop, kListeningModeRealtime
            };
            enum AecMode { kAecOff, kAecOnDeviceSide, kAecOnServerSide };
            enum AbortReason { kAbortReasonNone, kAbortReasonWakeWordDetected };
            struct AudioStreamPacket {};
            struct NotifySubtitle { uint32_t start_ms; std::string text; };
            struct Display {
                int transcripts = 0, conversation_shows = 0, message_emotions = 0;
                void ShowVoiceConversation() { ++conversation_shows; }
                void SetChatMessage(const char* role, const char* text) {
                    if ((strcmp(role, "assistant") == 0 || strcmp(role, "user") == 0) && *text)
                        ++transcripts;
                }
                void ClearChatMessages() {}
                void AddTextGlyphs(const std::vector<TextGlyph>&, uint8_t) {}
                void SetEmotion(const char* emotion) {
                    if (strcmp(emotion, "happy") == 0) ++message_emotions;
                }
                void SetStatus(const char*) {}
            };
            struct Led { void OnStateChanged() {} };
            struct Board {
                bool voice_enabled = true, allow_chat = true;
                int power_changes = 0;
                Display display;
                Led led;
                static Board& GetInstance() { static Board b; return b; }
                bool IsVoiceEnabled() const { return voice_enabled; }
                bool AllowChatControl(DeviceState) const { return allow_chat; }
                Display* GetDisplay() { return &display; }
                Led* GetLed() { return &led; }
                void SetPowerSaveLevel(PowerSaveLevel) { ++power_changes; }
            };
            struct AudioService {
                bool voice_processing = true, wake_detection = false, playback_idle = false;
                int mutations = 0, resets = 0, send_packets = 3, decoded_packets = 0;
                int persistent_voice_changes = 0, recorded_packets = 2, recorded_discards = 0;
                uint32_t playback_generation = 0;
                void SetVoiceEnabled(bool enabled) {
                    ++persistent_voice_changes;
                    if (!enabled) {
                        EnableVoiceProcessing(false); EnableWakeWordDetection(false); ResetDecoder();
                    }
                }
                void EnableVoiceProcessing(bool enabled) { voice_processing = enabled; ++mutations; }
                void EnableWakeWordDetection(bool enabled) { wake_detection = enabled; ++mutations; }
                bool IsAfeWakeWord() const { return false; }
                bool IsAudioProcessorRunning() const { return voice_processing; }
                bool IsPlaybackIdle() const { return playback_idle; }
                bool PopPacketFromSendQueue() {
                    if (!send_packets) return false;
                    --send_packets; ++mutations; return true;
                }
                void ResetDecoder() { ++resets; ++mutations; ++playback_generation; playback_idle = true; }
                uint32_t PlaybackGeneration() const { return playback_generation; }
                void DiscardRecordedAudio() {
                    ++recorded_discards; send_packets = 0; recorded_packets = 0;
                }
                void PushPacketToDecodeQueue(std::unique_ptr<AudioStreamPacket>, bool = false,
                                             std::optional<uint32_t> expected = std::nullopt) {
                    if (!expected || *expected == playback_generation) ++decoded_packets;
                }
                void EncodeWakeWord() { ++mutations; }
                std::string GetLastWakeWord() const { return "你好小智"; }
                void PlaySound(std::string_view) { ++mutations; }
                void EnableAudioTesting(bool) { ++mutations; }
            };
            struct Protocol {
                bool opened = true;
                std::string session = "session-current";
                int opens = 0, closes = 0, aborts = 0;
                std::function<void(std::unique_ptr<AudioStreamPacket>)> audio;
                std::function<void(const cJSON*)> json;
                std::function<void()> closed;
                void OnIncomingAudio(decltype(audio) cb) { audio = std::move(cb); }
                void OnIncomingJson(decltype(json) cb) { json = std::move(cb); }
                void OnAudioChannelClosed(decltype(closed) cb) { closed = std::move(cb); }
                const std::string& session_id() const { return session; }
                bool IsAudioChannelOpened() const { return opened; }
                bool OpenAudioChannel() { ++opens; opened = true; session = "session-next"; return true; }
                void CloseAudioChannel() { ++closes; opened = false; if (closed) closed(); }
                void SendAbortSpeaking(AbortReason reason) {
                    ++aborts;
                }
                void SendStartListening(ListeningMode) {}
            };
            struct StateMachine {
                DeviceState state = kDeviceStateIdle;
                DeviceState GetState() const { return state; }
            };
            class Application {
            public:
                StateMachine state_machine_;
                int state_changes = 0;
                bool aborted_ = false, voice_session_cancelled_ = false;
                std::atomic<uint32_t> voice_session_generation_{0};
                bool pending_listening_start_ = true, play_popup_on_listening_ = true;
                std::atomic<bool> shutting_down_{false};
                ListeningMode listening_mode_ = kListeningModeAutoStop;
                AecMode aec_mode_ = kAecOff;
                int clock_ticks_ = 0;
                int startup_hint_removals = 0;
                std::string last_error_message_;
                AudioService audio_service_;
                std::unique_ptr<Protocol> protocol_ = std::make_unique<Protocol>();
                std::deque<std::function<void()>> queued;
                std::function<void()> state_read_hook;
                DeviceState GetDeviceState() const {
                    const auto state = state_machine_.state;
                    if (state_read_hook) state_read_hook();
                    return state;
                }
                bool SetDeviceState(DeviceState next) {
                    if (shutting_down_) return false;
                    if (next != GetDeviceState()) { ++state_changes; state_machine_.state = next; }
                    return true;
                }
                void Schedule(std::function<void()>&& task) {
                    if (!shutting_down_) queued.push_back(std::move(task));
                }
                void Drain() {
                    auto tasks = std::move(queued); queued.clear();
                    for (auto& task : tasks) { if (shutting_down_) break; task(); }
                }
                void EndVoiceSession();
                void SetVoiceEnabled(bool);
                void AbortSpeaking(AbortReason);
                void ContinueOpenAudioChannel(ListeningMode);
                void ContinueWakeWordInvoke(const std::string&);
                void BeginWakeWordInvoke(const std::string&);
                void HandleWakeWordDetectedEvent();
                void HandleToggleChatEvent();
                void HandleStartListeningEvent();
                void HandleStateChangedEvent();
                void SetListeningMode(ListeningMode);
                ListeningMode GetDefaultListeningMode() const;
                void InitializeProtocol();
                void HideStartupWakeWordHint() { ++startup_hint_removals; }
                void StopNotification() {}
                void StartNotification(std::string, std::vector<NotifySubtitle>) {}
                void Reboot() {}
                void Alert(const char*, const char*, const char*, std::string_view) {}
                void StartListeningAudio() {}
                void ConfigureWakeWordForListening() {}
            };
            void Receive(Application& app, const char* type_name, const char* event,
                         const char* session_id = nullptr, cJSON::Kind session_kind = cJSON::String) {
                cJSON type(cJSON::String, type_name), state(cJSON::String, event);
                cJSON text(cJSON::String, "preserved transcript"), root(cJSON::Object);
                cJSON session(session_kind, session_id), emotion(cJSON::String, "happy");
                root.members = {{"type", &type}, {"state", &state}, {"text", &text}, {"emotion", &emotion}};
                if (session_id || session_kind != cJSON::String) root.members["session_id"] = &session;
                app.protocol_->json(&root);
            }
            void AssertStopped(Application& app) {
                assert(app.GetDeviceState() == kDeviceStateIdle);
                assert(!app.audio_service_.voice_processing && app.audio_service_.playback_idle);
                assert(app.audio_service_.resets == 1 && app.audio_service_.send_packets == 0);
                assert(app.audio_service_.recorded_packets == 0 && app.audio_service_.recorded_discards == 1);
                assert(!app.pending_listening_start_ && !app.play_popup_on_listening_);
                assert(Board::GetInstance().voice_enabled && app.audio_service_.persistent_voice_changes == 0);
                app.HandleStateChangedEvent();
                assert(app.audio_service_.wake_detection && !app.audio_service_.voice_processing);
            }
        '''
        checks = r'''
            int main(int argc, char** argv) {
                assert(argc == 2);
                const std::string scenario = argv[1];
                Application app;
                auto& board = Board::GetInstance();
                app.InitializeProtocol();
                app.state_machine_.state = kDeviceStateSpeaking;
                if (scenario == "queued") {
                    app.EndVoiceSession();
                    assert(app.queued.size() == 1);
                    assert(app.GetDeviceState() == kDeviceStateSpeaking);
                    assert(app.audio_service_.mutations == 0 && app.protocol_->closes == 0);
                    app.Drain(); AssertStopped(app);
                } else if (scenario == "connecting" || scenario == "listening" || scenario == "speaking") {
                    app.state_machine_.state = scenario == "connecting" ? kDeviceStateConnecting :
                                              scenario == "listening" ? kDeviceStateListening : kDeviceStateSpeaking;
                    app.EndVoiceSession(); app.Drain(); AssertStopped(app);
                    assert(app.protocol_->closes == 1 && !app.protocol_->opened);
                    assert(app.protocol_->aborts == (scenario == "speaking" ? 1 : 0));
                } else if (scenario == "no-protocol" || scenario == "closed-channel") {
                    if (scenario == "no-protocol") app.protocol_.reset();
                    else app.protocol_->opened = false;
                    app.EndVoiceSession(); app.Drain(); AssertStopped(app);
                    if (app.protocol_) assert(app.protocol_->closes == 0);
                } else if (scenario == "ignored-states") {
                    for (DeviceState state : {kDeviceStateUnknown, kDeviceStateStarting,
                         kDeviceStateWifiConfiguring, kDeviceStateIdle, kDeviceStateNotifying,
                         kDeviceStateUpgrading, kDeviceStateActivating, kDeviceStateAudioTesting,
                         kDeviceStateFatalError}) {
                        app.state_machine_.state = state;
                        app.EndVoiceSession(); app.Drain();
                        assert(app.GetDeviceState() == state && app.state_changes == 0);
                        assert(app.audio_service_.mutations == 0 && app.protocol_->closes == 0);
                        assert(!app.voice_session_cancelled_ && !app.aborted_);
                    }
                } else if (scenario == "disabled" || scenario == "queued-disabled" ||
                           scenario == "shutdown" || scenario == "queued-shutdown") {
                    if (scenario.starts_with("queued-")) app.EndVoiceSession();
                    if (scenario.ends_with("disabled")) board.voice_enabled = false;
                    else app.shutting_down_ = true;
                    if (!scenario.starts_with("queued-")) app.EndVoiceSession();
                    app.Drain();
                    assert(app.GetDeviceState() == kDeviceStateSpeaking && app.state_changes == 0);
                    assert(app.audio_service_.mutations == 0 && app.protocol_->closes == 0);
                    assert(!app.voice_session_cancelled_ && !app.aborted_);
                } else if (scenario == "second-stop") {
                    app.EndVoiceSession(); app.Drain(); AssertStopped(app);
                    const int mutations = app.audio_service_.mutations;
                    app.EndVoiceSession(); app.Drain();
                    assert(app.audio_service_.mutations == mutations && app.protocol_->closes == 1);
                } else if (scenario == "queued-open" || scenario == "queued-wake") {
                    app.state_machine_.state = kDeviceStateConnecting;
                    app.protocol_->opened = false;
                    app.EndVoiceSession();
                    if (scenario == "queued-open") app.Schedule([&]() {
                        app.ContinueOpenAudioChannel(kListeningModeAutoStop);
                    });
                    else app.Schedule([&]() { app.ContinueWakeWordInvoke("你好小智"); });
                    app.Drain(); AssertStopped(app);
                    assert(app.protocol_->opens == 0 && board.power_changes == 0);
                } else if (scenario == "late-audio") {
                    app.EndVoiceSession(); app.Drain();
                    app.protocol_->audio(std::make_unique<AudioStreamPacket>());
                    assert(app.audio_service_.decoded_packets == 0);
                } else if (scenario == "audio-stop-between-state-check-and-push") {
                    app.state_read_hook = [&]() {
                        app.state_read_hook = nullptr;
                        app.state_machine_.state = kDeviceStateIdle;
                        app.audio_service_.ResetDecoder();
                    };
                    app.protocol_->audio(std::make_unique<AudioStreamPacket>());
                    assert(app.audio_service_.decoded_packets == 0);
                } else if (scenario == "disable-enable-old-callbacks") {
                    Receive(app, "tts", "start"); Receive(app, "tts", "sentence_start");
                    Receive(app, "stt", ""); Receive(app, "llm", "");
                    board.voice_enabled = false; app.SetVoiceEnabled(false);
                    assert(app.audio_service_.recorded_packets == 0 && app.audio_service_.send_packets == 0);
                    board.voice_enabled = true; app.SetVoiceEnabled(true); app.Drain();
                    assert(app.GetDeviceState() == kDeviceStateIdle);
                    assert(board.display.transcripts == 0 && board.display.message_emotions == 0);
                    app.HandleStartListeningEvent(); app.Drain();
                    Receive(app, "tts", "start"); Receive(app, "tts", "sentence_start");
                    Receive(app, "stt", ""); app.Drain();
                    assert(app.GetDeviceState() == kDeviceStateSpeaking && !app.aborted_);
                    assert(board.display.transcripts == 2);
                } else if (scenario == "disabled-queued-transcript") {
                    Receive(app, "tts", "sentence_start"); Receive(app, "stt", "");
                    Receive(app, "llm", ""); board.voice_enabled = false; app.Drain();
                    assert(board.display.transcripts == 0 && board.display.message_emotions == 0);
                } else if (scenario == "late-tts" || scenario == "queued-tts" ||
                           scenario == "late-transcript" || scenario == "queued-transcript") {
                    app.EndVoiceSession();
                    if (scenario.starts_with("late-")) app.Drain();
                    if (scenario.ends_with("tts")) {
                        Receive(app, "tts", "start"); Receive(app, "tts", "stop");
                    } else {
                        Receive(app, "tts", "sentence_start"); Receive(app, "stt", "");
                    }
                    app.Drain();
                    assert(app.GetDeviceState() == kDeviceStateIdle && app.aborted_);
                    assert(board.display.transcripts == 0);
                } else if (scenario == "next-toggle" || scenario == "next-listen" ||
                           scenario == "next-wake") {
                    app.EndVoiceSession(); app.Drain();
                    if (scenario == "next-toggle") app.HandleToggleChatEvent();
                    else if (scenario == "next-listen") app.HandleStartListeningEvent();
                    else app.BeginWakeWordInvoke("你好小智");
                    app.Drain();
                    assert(app.GetDeviceState() == kDeviceStateListening);
                    Receive(app, "tts", "start"); app.Drain();
                    assert(app.GetDeviceState() == kDeviceStateSpeaking && !app.aborted_);
                    Receive(app, "tts", "sentence_start"); Receive(app, "stt", ""); app.Drain();
                    assert(board.display.transcripts == 2);
                } else if (scenario == "hint-toggle" || scenario == "hint-listen" || scenario == "hint-wake") {
                    app.state_machine_.state = kDeviceStateIdle;
                    if (scenario == "hint-toggle") app.HandleToggleChatEvent();
                    else if (scenario == "hint-listen") app.HandleStartListeningEvent();
                    else app.BeginWakeWordInvoke("你好小智");
                    app.Drain();
                    assert(app.GetDeviceState() == kDeviceStateListening && app.startup_hint_removals == 1);
                } else if (scenario == "hint-rejected-or-active") {
                    app.state_machine_.state = kDeviceStateIdle;
                    board.allow_chat = false;
                    app.HandleToggleChatEvent(); app.HandleStartListeningEvent();
                    board.allow_chat = true; board.voice_enabled = false;
                    app.HandleToggleChatEvent(); app.HandleStartListeningEvent(); app.HandleWakeWordDetectedEvent();
                    board.voice_enabled = true;
                    app.state_machine_.state = kDeviceStateSpeaking;
                    app.HandleToggleChatEvent(); app.HandleStartListeningEvent();
                    app.Drain();
                    assert(app.startup_hint_removals == 0);
                } else if (scenario == "old-close-after-new-wake") {
                    app.EndVoiceSession(); app.Drain();
                    assert(app.queued.size() == 1 && "closing the old session queues its close callback");
                    app.BeginWakeWordInvoke("你好小智"); app.Drain();
                    assert(app.GetDeviceState() == kDeviceStateListening && app.protocol_->opens == 1);
                } else if (scenario == "session-current" || scenario == "session-absent") {
                    app.state_machine_.state = kDeviceStateListening;
                    const char* id = scenario == "session-current" ? "session-current" : nullptr;
                    Receive(app, "tts", "start", id); Receive(app, "tts", "sentence_start", id);
                    Receive(app, "stt", "", id); Receive(app, "llm", "", id); app.Drain();
                    assert(app.GetDeviceState() == kDeviceStateSpeaking && !app.aborted_);
                    assert(board.display.transcripts == 2 && board.display.message_emotions == 1);
                } else if (scenario == "session-old-after-new") {
                    app.EndVoiceSession(); app.Drain();
                    app.BeginWakeWordInvoke("你好小智"); app.Drain();
                    Receive(app, "tts", "start", "session-current");
                    Receive(app, "tts", "stop", "session-current");
                    Receive(app, "tts", "sentence_start", "session-current");
                    Receive(app, "stt", "", "session-current"); Receive(app, "llm", "", "session-current");
                    app.Drain();
                    assert(app.GetDeviceState() == kDeviceStateListening && app.aborted_);
                    assert(board.display.transcripts == 0 && board.display.message_emotions == 0);
                    Receive(app, "tts", "start", "session-next");
                    Receive(app, "tts", "sentence_start", "session-next");
                    Receive(app, "stt", "", "session-next"); Receive(app, "llm", "", "session-next");
                    app.Drain();
                    assert(app.GetDeviceState() == kDeviceStateSpeaking && !app.aborted_);
                    assert(board.display.transcripts == 2 && board.display.message_emotions == 1);
                } else if (scenario == "session-malformed-number" || scenario == "session-malformed-empty" ||
                           scenario == "session-changed-before-execution") {
                    app.state_machine_.state = kDeviceStateListening; app.aborted_ = true;
                    const bool changed = scenario == "session-changed-before-execution";
                    const char* id = changed ? "session-current" : "";
                    auto kind = scenario == "session-malformed-number" ? cJSON::Number : cJSON::String;
                    Receive(app, "tts", "start", id, kind); Receive(app, "tts", "stop", id, kind);
                    Receive(app, "tts", "sentence_start", id, kind);
                    Receive(app, "stt", "", id, kind); Receive(app, "llm", "", id, kind);
                    if (changed) app.protocol_->session = "replaced-session";
                    app.Drain();
                    assert(app.GetDeviceState() == kDeviceStateListening && app.aborted_);
                    assert(board.display.transcripts == 0 && board.display.message_emotions == 0);
                } else if (scenario == "old-before-stop" || scenario == "old-after-stop") {
                    // The new start event runs before MAIN_EVENT_SCHEDULE, so an old
                    // callback can execute after the next session has already started.
                    if (scenario == "old-after-stop") { app.EndVoiceSession(); app.Drain(); }
                    Receive(app, "tts", "start"); Receive(app, "tts", "stop");
                    Receive(app, "tts", "sentence_start"); Receive(app, "stt", "");
                    auto old_callbacks = std::move(app.queued); app.queued.clear();
                    if (scenario == "old-before-stop") { app.EndVoiceSession(); app.Drain(); }
                    app.HandleStartListeningEvent(); app.Drain();
                    app.queued = std::move(old_callbacks); app.Drain();
                    assert(app.GetDeviceState() == kDeviceStateListening && app.aborted_);
                    assert(board.display.transcripts == 0);
                    Receive(app, "tts", "start"); Receive(app, "tts", "sentence_start");
                    Receive(app, "stt", ""); app.Drain();
                    assert(app.GetDeviceState() == kDeviceStateSpeaking && !app.aborted_);
                    assert(board.display.transcripts == 2);
                } else if (scenario == "rejected-toggle" || scenario == "rejected-listen") {
                    app.EndVoiceSession(); app.Drain();
                    board.allow_chat = false;
                    if (scenario == "rejected-toggle") app.HandleToggleChatEvent();
                    else app.HandleStartListeningEvent();
                    board.allow_chat = true;
                    Receive(app, "tts", "start"); Receive(app, "tts", "sentence_start"); app.Drain();
                    assert(app.GetDeviceState() == kDeviceStateIdle && app.aborted_);
                    assert(board.display.transcripts == 0 && app.protocol_->opens == 0);
                } else if (scenario == "wake-page-idle" || scenario == "wake-page-speaking" ||
                           scenario == "wake-page-listening" || scenario == "wake-page-invalid") {
                    app.state_machine_.state = scenario == "wake-page-idle" ? kDeviceStateIdle :
                        scenario == "wake-page-speaking" ? kDeviceStateSpeaking :
                        scenario == "wake-page-listening" ? kDeviceStateListening : kDeviceStateWifiConfiguring;
                    app.HandleWakeWordDetectedEvent(); app.Drain();
                    assert(board.display.conversation_shows == (scenario == "wake-page-invalid" ? 0 : 1));
                } else {
                    assert(scenario == "upstream-idle-tts");
                    app.state_machine_.state = kDeviceStateIdle;
                    Receive(app, "tts", "start"); app.Drain();
                    assert(app.GetDeviceState() == kDeviceStateSpeaking && !app.aborted_);
                    Receive(app, "tts", "sentence_start"); Receive(app, "stt", ""); app.Drain();
                    assert(board.display.transcripts == 2);
                }
            }
        '''
        cls.directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.directory.cleanup)
        path = Path(cls.directory.name)
        driver = path / "air_chat_stop.cc"
        driver.write_text(textwrap.dedent(platform) + methods + callbacks + textwrap.dedent(checks))
        cls.executable = path / "air_chat_stop"
        compiled = subprocess.run(
            compiler + ["-std=c++23", "-I", str(ROOT / "main"), str(driver), "-o", str(cls.executable)],
            capture_output=True, text=True,
        )
        if compiled.returncode:
            raise AssertionError(compiled.stdout + compiled.stderr)

    def scenario(self, name):
        result = subprocess.run([str(self.executable), name], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_stop_runs_only_on_the_application_task(self):
        self.scenario("queued")

    def test_stop_ends_each_active_session_and_preserves_wake(self):
        for state in ("connecting", "listening", "speaking"):
            with self.subTest(state=state):
                self.scenario(state)

    def test_stop_without_protocol_still_restores_idle_audio(self):
        self.scenario("no-protocol")

    def test_stop_when_channel_is_already_closed(self):
        self.scenario("closed-channel")

    def test_stop_does_not_change_non_session_states(self):
        self.scenario("ignored-states")

    def test_disabled_voice_is_unchanged_at_request_and_execution(self):
        for name in ("disabled", "queued-disabled"):
            with self.subTest(name=name):
                self.scenario(name)

    def test_shutdown_is_unchanged_at_request_and_execution(self):
        for name in ("shutdown", "queued-shutdown"):
            with self.subTest(name=name):
                self.scenario(name)

    def test_second_stop_has_no_additional_side_effects(self):
        self.scenario("second-stop")

    def test_canceled_queued_open_does_not_start_conversation(self):
        self.scenario("queued-open")

    def test_canceled_queued_wake_does_not_start_conversation(self):
        self.scenario("queued-wake")

    def test_late_audio_cannot_resume_playback(self):
        self.scenario("late-audio")

    def test_audio_received_before_stop_cannot_enter_the_new_playback_generation(self):
        self.scenario("audio-stop-between-state-check-and-push")

    def test_disable_then_enable_keeps_old_callbacks_canceled_and_new_start_usable(self):
        self.scenario("disable-enable-old-callbacks")

    def test_queued_transcripts_and_emotion_recheck_voice_setting(self):
        self.scenario("disabled-queued-transcript")

    def test_late_and_queued_tts_cannot_restart_a_stopped_session(self):
        for name in ("late-tts", "queued-tts"):
            with self.subTest(name=name):
                self.scenario(name)

    def test_late_and_queued_transcripts_cannot_leak_after_stop(self):
        for name in ("late-transcript", "queued-transcript"):
            with self.subTest(name=name):
                self.scenario(name)

    def test_next_user_or_wake_start_restores_normal_callbacks(self):
        for name in ("next-toggle", "next-listen", "next-wake"):
            with self.subTest(name=name):
                self.scenario(name)

    def test_rejected_user_start_does_not_rearm_canceled_callbacks(self):
        for name in ("rejected-toggle", "rejected-listen"):
            with self.subTest(name=name):
                self.scenario(name)

    def test_old_callbacks_stay_canceled_after_an_immediate_new_session(self):
        for name in ("old-before-stop", "old-after-stop"):
            with self.subTest(name=name):
                self.scenario(name)

    def test_old_channel_close_cannot_cancel_the_next_wake(self):
        self.scenario("old-close-after-new-wake")

    def test_accepted_fresh_voice_starts_remove_the_startup_hint(self):
        for name in ("hint-toggle", "hint-listen", "hint-wake"):
            with self.subTest(name=name):
                self.scenario(name)

    def test_rejected_or_active_voice_controls_preserve_the_startup_hint(self):
        self.scenario("hint-rejected-or-active")

    def test_matching_and_absent_session_ids_keep_voice_json_compatible(self):
        for name in ("session-current", "session-absent"):
            with self.subTest(name=name):
                self.scenario(name)

    def test_explicit_old_session_id_is_rejected_after_next_start(self):
        self.scenario("session-old-after-new")

    def test_malformed_explicit_session_id_is_rejected(self):
        for name in ("session-malformed-number", "session-malformed-empty"):
            with self.subTest(name=name):
                self.scenario(name)

    def test_explicit_session_id_is_checked_when_queued_work_executes(self):
        self.scenario("session-changed-before-execution")

    def test_upstream_idle_tts_still_starts_without_a_user_stop(self):
        self.scenario("upstream-idle-tts")

    def test_real_wake_reopens_conversation_only_in_accepted_states(self):
        for name in ("wake-page-idle", "wake-page-speaking", "wake-page-listening", "wake-page-invalid"):
            with self.subTest(name=name):
                self.scenario(name)
