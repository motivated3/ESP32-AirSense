"""Run the real channel-open path against an MQTT connection that stops replying."""

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


class MqttHelloRecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shlex.split(os.environ.get("CXX", "c++"))
        if not compiler or shutil.which(compiler[0]) is None:
            raise unittest.SkipTest("requires a host C++23 compiler")
        source = (ROOT / "main/protocols/mqtt_protocol.cc").read_text()
        method = definition(source, "bool MqttProtocol::OpenAudioChannel()")
        disconnected = definition(source, "mqtt_->OnDisconnected(") + ");"
        packet = definition((ROOT / "main/protocols/protocol.h").read_text(),
                            "struct AudioStreamPacket") + ";\n"
        platform = r'''
            #include <arpa/inet.h>
            #include <cassert>
            #include <atomic>
            #include <chrono>
            #include <cstdint>
            #include <cstring>
            #include <deque>
            #include <functional>
            #include <memory>
            #include <mutex>
            #include <string>
            #include <vector>
            #define ESP_LOGI(...) ((void)0)
            #define ESP_LOGE(...) ((void)0)
            #define ESP_LOGW(...) ((void)0)
            #define TAG "HostMqttHello"
            using EventBits_t = uint32_t;
            constexpr int pdTRUE = 1, pdFALSE = 0, MQTT_PROTOCOL_SERVER_HELLO_EVENT = 1;
            constexpr int MQTT_RECONNECT_INTERVAL_MS = 60000;
            void esp_timer_start_once(int, int) {}
            constexpr int pdMS_TO_TICKS(int ms) { return ms; }
            bool server_hello = false;
            void xEventGroupClearBits(int, int) { server_hello = false; }
            EventBits_t xEventGroupWaitBits(int, int, int, int, int) {
                return server_hello ? MQTT_PROTOCOL_SERVER_HELLO_EVENT : 0;
            }
            namespace Lang::Strings {
                constexpr const char* SERVER_TIMEOUT = "timeout";
                [[maybe_unused]] constexpr const char* SERVER_ERROR = "server error";
            }
            struct Application {
                std::deque<std::function<void()>> tasks;
                static Application& GetInstance() { static Application app; return app; }
                void Schedule(std::function<void()>&& task) { tasks.push_back(std::move(task)); }
                void Drain() {
                    auto queued = std::move(tasks); tasks.clear();
                    for (auto& task : queued) task();
                }
            };
            struct Error { std::string ToString() const { return "failed"; } };
            struct Connected {
                explicit operator bool() const { return true; }
                Error error() const { return {}; }
            };
            struct Udp {
                void OnMessage(std::function<void(const std::string&)>) {}
                Connected Connect(const std::string&, int) { return {}; }
            };
            struct Network { std::unique_ptr<Udp> CreateUdp(int) { return std::make_unique<Udp>(); } };
            struct Board {
                Network network;
                static Board& GetInstance() { static Board board; return board; }
                Network* GetNetwork() { return &network; }
            };
            struct Mqtt {
                int generation = 0;
                bool connected = true;
                bool IsConnected() const { return connected; }
                std::function<void()> disconnected;
                void OnDisconnected(std::function<void()> callback) { disconnected = std::move(callback); }
                void Disconnect() { connected = false; if (disconnected) disconnected(); }
            };
        '''
        protocol = r'''
            struct MqttProtocol {
                std::unique_ptr<Mqtt> mqtt_ = std::make_unique<Mqtt>();
                std::shared_ptr<Udp> udp_;
                std::shared_ptr<std::atomic<bool>> alive_ = std::make_shared<std::atomic<bool>>(true);
                std::mutex channel_mutex_;
                bool error_occurred_ = false, initial_hello = false, reconnect_ok = true;
                int reconnects = 0, opened = 0, closed = 0, reconnect_timer_ = 0;
                int event_group_handle_ = 0, server_sample_rate_ = 24000, server_frame_duration_ = 60;
                int udp_port_ = 9000;
                std::string session_id_ = "old", udp_server_ = "test.invalid";
                uint32_t remote_sequence_ = 0;
                std::chrono::steady_clock::time_point last_incoming_time_;
                std::function<void()> on_audio_channel_opened_ = [this]() { ++opened; };
                std::function<void(std::unique_ptr<AudioStreamPacket>)> on_incoming_audio_;
                std::function<void()> on_disconnected_;
                void RegisterDisconnected();
                void CloseAudioChannel(bool) { udp_.reset(); ++closed; }
                bool StartMqttClient(bool) {
                    ++reconnects;
                    if (!reconnect_ok) return false;
                    mqtt_ = std::make_unique<Mqtt>();
                    mqtt_->generation = reconnects;
                    return true;
                }
                std::string GetHelloMessage() { return "hello"; }
                bool SendText(const std::string&) {
                    server_hello = mqtt_->generation != 0 || initial_hello;
                    return true;
                }
                void SetError(const char*) { error_occurred_ = true; }
                bool CryptAesCtr(const uint8_t*, size_t, const uint8_t*, uint8_t*) { return false; }
                bool OpenAudioChannel();
            };
        '''
        checks = r'''
            int main(int argc, char** argv) {
                assert(argc == 2);
                const std::string scenario = argv[1];
                MqttProtocol protocol;
                if (scenario.find("control-") == 0) {
                    protocol.initial_hello = true;
                    if (scenario != "control-idle") assert(protocol.OpenAudioChannel());
                    protocol.RegisterDisconnected();
                    protocol.mqtt_->Disconnect();
                    assert(protocol.closed == 0 && "channel cleanup must run on the application task");
                    if (scenario == "control-replaced") {
                        protocol.mqtt_->connected = true;
                        assert(protocol.OpenAudioChannel());
                    } else if (scenario == "control-destroyed") *protocol.alive_ = false;
                    Application::GetInstance().Drain();
                    if (scenario == "control-active") {
                        assert(protocol.closed == 1 && protocol.error_occurred_ && !protocol.udp_);
                    } else {
                        assert(protocol.closed == 0 && !protocol.error_occurred_);
                    }
                } else if (scenario == "healthy") {
                    protocol.initial_hello = true;
                    assert(protocol.OpenAudioChannel());
                    assert(protocol.OpenAudioChannel());
                    assert(protocol.reconnects == 0 && protocol.opened == 2);
                } else if (scenario == "disconnected") {
                    protocol.mqtt_->connected = false;
                    assert(protocol.OpenAudioChannel());
                    assert(protocol.reconnects == 1 && protocol.opened == 1);
                } else {
                    assert(!protocol.OpenAudioChannel());
                    assert(protocol.error_occurred_ && protocol.mqtt_->IsConnected());
                    assert(protocol.opened == 0 && !protocol.udp_);
                    if (scenario == "retry-failed") protocol.reconnect_ok = false;
                    const bool recovered = protocol.OpenAudioChannel();
                    assert(protocol.reconnects == 1 && "hello retry must rebuild a stale MQTT client");
                    assert(recovered == (scenario == "retry"));
                    assert(protocol.opened == (recovered ? 1 : 0));
                    if (recovered) assert(!protocol.error_occurred_ && protocol.udp_);
                }
            }
        '''
        cls.directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.directory.cleanup)
        folder = Path(cls.directory.name)
        driver = folder / "mqtt_hello.cc"
        driver.write_text(textwrap.dedent(platform) + packet + textwrap.dedent(protocol)
                          + "\nvoid MqttProtocol::RegisterDisconnected() {\n" + disconnected + "\n}\n"
                          + method + textwrap.dedent(checks))
        cls.executable = folder / "mqtt_hello"
        result = subprocess.run(compiler + ["-std=c++23", "-Wall", "-Wextra", "-Werror",
                                           "-Wno-unused-parameter", str(driver), "-o", str(cls.executable)],
                                capture_output=True, text=True)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)

    def scenario(self, name):
        result = subprocess.run([str(self.executable), name], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_timeout_rebuilds_a_client_that_still_reports_connected(self):
        self.scenario("retry")

    def test_failed_reconnect_does_not_start_udp(self):
        self.scenario("retry-failed")

    def test_healthy_connection_is_reused(self):
        self.scenario("healthy")

    def test_disconnected_client_reconnects(self):
        self.scenario("disconnected")

    def test_control_disconnect_ends_active_audio_session_on_application_task(self):
        self.scenario("control-active")

    def test_old_disconnect_does_not_close_replacement_audio_session(self):
        self.scenario("control-replaced")

    def test_queued_disconnect_is_safe_after_destruction(self):
        self.scenario("control-destroyed")

    def test_idle_control_disconnect_does_not_raise_a_voice_error(self):
        self.scenario("control-idle")


if __name__ == "__main__":
    unittest.main()
