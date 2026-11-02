"""Exercise the production application shutdown boundary with host dependencies."""

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


class AirShutdownTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shlex.split(os.environ.get("CXX", "c++"))
        if not compiler or shutil.which(compiler[0]) is None:
            raise unittest.SkipTest("requires a host C++23 compiler")
        source = (ROOT / "main/application.cc").read_text(encoding="utf-8")
        methods = "\n".join(definition(source, signature) for signature in (
            "void Application::PrepareForShutdown()",
            "void Application::Schedule(",
            "void Application::SetVoiceEnabled(",
        ))
        readiness = definition((ROOT / "main/application.h").read_text(), "bool IsShutdownReady() const")
        methods += "\n" + readiness.replace("bool IsShutdownReady()", "bool Application::IsShutdownReady()")
        platform = r'''
            #include <atomic>
            #include <cassert>
            #include <cstdint>
            #include <deque>
            #include <functional>
            #include <memory>
            #include <mutex>
            #include <string>
            #include <utility>
            #include "device_state.h"
            #define TAG "HostShutdown"
            #define ESP_LOGI(...) ((void)0)
            #define ESP_LOGW(...) ((void)0)
            #define ESP_LOGE(...) ((void)0)
            constexpr uint32_t MAIN_EVENT_SCHEDULE = 1 << 4;
            void xEventGroupSetBits(uint32_t* events, uint32_t bits) { *events |= bits; }
            struct AudioService {
                bool voice_enabled = true, wake_enabled = false;
                int stop_calls = 0, enable_calls = 0;
                void SetVoiceEnabled(bool enabled) { voice_enabled = enabled; if (enabled) ++enable_calls; }
                void DiscardRecordedAudio() {}
                void EnableWakeWordDetection(bool enabled) { wake_enabled = enabled; }
                void Stop() { ++stop_calls; }
                bool IsStopped() const { return stop_calls != 0; }
            };
            int protocol_destructions = 0;
            struct Protocol {
                bool open = true;
                int close_calls = 0;
                ~Protocol() { ++protocol_destructions; }
                bool IsAudioChannelOpened() const { return open; }
                void CloseAudioChannel() { ++close_calls; open = false; }
            };
            class Application {
            public:
                std::atomic<bool> shutting_down_{false}, activation_running_{false};
                bool voice_session_cancelled_ = false;
                std::atomic<uint32_t> voice_session_generation_{0};
                AudioService audio_service_;
                std::unique_ptr<Protocol> protocol_ = std::make_unique<Protocol>();
                std::mutex mutex_;
                std::deque<std::function<void()>> main_tasks_;
                uint32_t events = 0;
                uint32_t* event_group_ = &events;
                DeviceState state = kDeviceStateIdle;
                int notification_stops = 0;
                DeviceState GetDeviceState() const { return state; }
                bool SetDeviceState(DeviceState next) { state = next; return true; }
                void StopNotification() { ++notification_stops; state = kDeviceStateIdle; }
                void PrepareForShutdown();
                bool IsShutdownReady() const;
                void Schedule(std::function<void()>&& callback);
                void SetVoiceEnabled(bool enabled);
                void Drain() {
                    std::deque<std::function<void()>> tasks;
                    tasks.swap(main_tasks_);
                    for (auto& task : tasks) task();
                }
            };
        '''
        checks = r'''
            int main(int argc, char** argv) {
                assert(argc == 2);
                std::string scenario = argv[1];
                Application app;
                if (scenario == "stops-audio") {
                    app.state = kDeviceStateNotifying;
                    app.PrepareForShutdown();
                    assert(!app.audio_service_.voice_enabled);
                    assert(app.audio_service_.stop_calls == 1);
                    assert(app.notification_stops == 1);
                } else if (scenario == "idempotent") {
                    app.PrepareForShutdown();
                    app.PrepareForShutdown();
                    assert(app.audio_service_.stop_calls == 1 && "shutdown preparation must run once");
                } else if (scenario == "preserves-protocol") {
                    // The activation task may still own/use the live protocol object.
                    app.activation_running_.store(true);
                    auto* protocol = app.protocol_.get();
                    app.PrepareForShutdown();
                    assert(app.protocol_.get() == protocol && protocol_destructions == 0 &&
                           "shutdown must not reset a protocol still shared with activation");
                    assert(app.audio_service_.stop_calls == 1);
                } else if (scenario == "waits-activation") {
                    app.activation_running_ = true;
                    app.PrepareForShutdown();
                    assert(!app.IsShutdownReady() && "active activation is not graceful completion");
                    app.activation_running_ = false;
                    assert(app.IsShutdownReady());
                } else if (scenario == "rejects-new-work") {
                    app.PrepareForShutdown();
                    app.events = 0;
                    app.Schedule([&app]() { app.SetVoiceEnabled(true); });
                    assert(app.main_tasks_.empty() && "shutdown must reject newly scheduled tasks");
                    assert(!(app.events & MAIN_EVENT_SCHEDULE));
                } else {
                    assert(scenario == "rejects-voice-reenable");
                    // Model a task already extracted by the main loop before shutdown.
                    app.Schedule([&app]() { app.SetVoiceEnabled(true); });
                    auto tasks = std::move(app.main_tasks_);
                    app.main_tasks_.clear();
                    assert(tasks.size() == 1);
                    app.PrepareForShutdown();
                    for (auto& task : tasks) task();
                    assert(!app.audio_service_.voice_enabled && !app.audio_service_.wake_enabled &&
                           app.audio_service_.enable_calls == 0 &&
                           "already queued work must not re-enable audio after shutdown");
                }
            }
        '''
        cls.directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.directory.cleanup)
        path = Path(cls.directory.name)
        driver = path / "air_shutdown.cc"
        driver.write_text(textwrap.dedent(platform) + methods + textwrap.dedent(checks), encoding="utf-8")
        cls.executable = path / "air_shutdown"
        compiled = subprocess.run(
            compiler + ["-std=c++23", "-I", str(ROOT / "main"), str(driver), "-o", str(cls.executable)],
            capture_output=True, text=True,
        )
        if compiled.returncode:
            raise AssertionError(compiled.stdout + compiled.stderr)

    def run_scenario(self, scenario):
        result = subprocess.run([str(self.executable), scenario], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_shutdown_stops_voice_and_notification(self):
        self.run_scenario("stops-audio")

    def test_shutdown_preparation_is_idempotent(self):
        self.run_scenario("idempotent")

    def test_shutdown_retains_protocol_while_activation_may_use_it(self):
        self.run_scenario("preserves-protocol")

    def test_shutdown_waits_for_activation_worker_to_finish(self):
        self.run_scenario("waits-activation")

    def test_shutdown_rejects_new_scheduled_work(self):
        self.run_scenario("rejects-new-work")

    def test_already_queued_work_cannot_reenable_voice_after_shutdown(self):
        self.run_scenario("rejects-voice-reenable")
