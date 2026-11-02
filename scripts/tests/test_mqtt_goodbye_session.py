"""Exercise the real MQTT JSON callback and deferred goodbye against channel changes."""

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


class MqttGoodbyeSessionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cxx = shlex.split(os.environ.get("CXX", "c++"))
        cc = shlex.split(os.environ.get("CC", "cc"))
        if any(not command or shutil.which(command[0]) is None for command in (cc, cxx)):
            raise unittest.SkipTest("requires host C and C++23 compilers")
        source = (ROOT / "main/protocols/mqtt_protocol.cc").read_text()
        callback = definition(source, "mqtt_->OnMessage(") + ");"
        platform = r'''
            #include <cassert>
            #include <chrono>
            #include <deque>
            #include <functional>
            #include <memory>
            #include <string>
            #include <utility>
            #include "cJSON.h"
            #define TAG "HostMqttGoodbye"
            #define ESP_LOGI(...) ((void)0)
            #define ESP_LOGE(...) ((void)0)
            struct Application {
                std::deque<std::function<void()>> tasks;
                static Application& GetInstance() { static Application app; return app; }
                void Schedule(std::function<void()>&& task) { tasks.push_back(std::move(task)); }
                void Drain() {
                    auto ready = std::move(tasks); tasks.clear();
                    for (auto& task : ready) task();
                }
            };
            struct Mqtt {
                std::function<void(const std::string&, const std::string&)> message;
                void OnMessage(decltype(message) callback) { message = std::move(callback); }
            };
            struct MqttProtocol {
                std::unique_ptr<Mqtt> mqtt_ = std::make_unique<Mqtt>();
                std::shared_ptr<bool> alive_ = std::make_shared<bool>(true);
                std::string session_id_ = "old";
                bool opened = true, sent_goodbye = true;
                int closes = 0, hellos = 0, forwarded = 0;
                std::chrono::steady_clock::time_point last_incoming_time_;
                std::function<void(const cJSON*)> on_incoming_json_ = [this](const cJSON*) { ++forwarded; };
                bool IsAudioChannelOpened() const { return opened; }
                void CloseAudioChannel(bool send_goodbye) { ++closes; sent_goodbye = send_goodbye; opened = false; }
                void ParseServerHello(const cJSON*) { ++hellos; }
                void Register();
                void Receive(const char* json) { mqtt_->message("server", json); }
            };
            void MqttProtocol::Register() {
        '''
        checks = r'''
            }
            int main(int argc, char** argv) {
                assert(argc == 2);
                const std::string scenario = argv[1];
                MqttProtocol protocol;
                protocol.Register();
                if (scenario == "missing-id" || scenario == "invalid-id") {
                    protocol.Receive(scenario == "missing-id" ? R"({"type":"goodbye"})" : R"({"type":"goodbye","session_id":12})");
                } else if (scenario == "other-routes") {
                    protocol.Receive(R"({"type":"hello"})");
                    protocol.Receive(R"({"type":"stt","session_id":"old","text":"hello"})");
                    assert(protocol.hellos == 1 && protocol.forwarded == 1);
                } else {
                    protocol.Receive(R"({"type":"goodbye","session_id":"old"})");
                    assert(protocol.closes == 0 && "goodbye must remain scheduled on the application task");
                    if (scenario == "closed-gap") protocol.opened = false;
                    else if (scenario == "new-session") protocol.session_id_ = "new";
                    else if (scenario == "destroyed") *protocol.alive_ = false;
                    else if (scenario == "duplicate") protocol.Receive(R"({"type":"goodbye","session_id":"old"})");
                    else assert(scenario == "same-session");
                }
                Application::GetInstance().Drain();
                const bool should_close = scenario == "same-session" || scenario == "duplicate";
                assert(protocol.closes == (should_close ? 1 : 0) && "stale goodbye must not close a replacement or already closed channel");
                if (should_close) assert(!protocol.sent_goodbye && !protocol.opened);
            }
        '''
        cls.directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.directory.cleanup)
        path = Path(cls.directory.name)
        driver = path / "mqtt_goodbye.cc"
        driver.write_text(textwrap.dedent(platform) + callback + textwrap.dedent(checks))
        cjson = ROOT / "managed_components/espressif__cjson/cJSON"
        obj = path / "cJSON.o"
        cls.executable = path / "mqtt_goodbye"
        commands = (
            cc + ["-I", str(cjson), "-c", str(cjson / "cJSON.c"), "-o", str(obj)],
            cxx + ["-std=c++23", "-Wall", "-Wextra", "-Werror", "-Wno-unused-parameter", "-I", str(cjson), str(driver), str(obj), "-o", str(cls.executable)],
        )
        for command in commands:
            compiled = subprocess.run(command, capture_output=True, text=True)
            if compiled.returncode:
                raise AssertionError(compiled.stdout + compiled.stderr)

    def scenario(self, name):
        result = subprocess.run([str(self.executable), name], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_old_goodbye_cannot_close_during_next_wake_connecting_gap(self):
        self.scenario("closed-gap")

    def test_old_goodbye_cannot_close_new_session(self):
        self.scenario("new-session")

    def test_current_session_goodbye_closes_without_reply(self):
        self.scenario("same-session")

    def test_duplicate_goodbye_does_not_signal_another_close(self):
        self.scenario("duplicate")

    def test_legacy_goodbye_without_session_id_remains_ignored(self):
        self.scenario("missing-id")

    def test_invalid_session_id_remains_ignored(self):
        self.scenario("invalid-id")

    def test_destroyed_protocol_does_not_close(self):
        self.scenario("destroyed")

    def test_hello_and_other_json_keep_existing_routes(self):
        self.scenario("other-routes")
