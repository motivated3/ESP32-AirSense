"""Exercise the real connected-event handler after a queued event becomes stale."""

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


class AirNetworkStateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shlex.split(os.environ.get("CXX", "c++"))
        if not compiler or not shutil.which(compiler[0]):
            raise unittest.SkipTest("requires a host C++ compiler")
        method = definition((ROOT / "main/application.cc").read_text(),
                            "void Application::HandleNetworkConnectedEvent()")
        platform = r'''
            #include <atomic>
            #include <cassert>
            #include <string>
            #include "device_state.h"
            #define ESP_LOGI(...) ((void)0)
            #define ESP_LOGW(...) ((void)0)
            using TaskHandle_t = void*;
            constexpr int pdPASS = 1;
            int task_creations = 0;
            int xTaskCreate(void (*)(void*), const char*, int, void*, int, TaskHandle_t* out) {
                ++task_creations;
                *out = reinterpret_cast<void*>(1);
                return pdPASS;
            }
            void vTaskDelete(void*) {}
            struct Display {
                int updates = 0;
                void UpdateStatusBar(bool) { ++updates; }
            };
            struct Board {
                bool connected = false;
                Display display;
                static Board& GetInstance() { static Board board; return board; }
                bool IsNetworkConnected() const { return connected; }
                Display* GetDisplay() { return &display; }
            };
            struct Application {
                DeviceState state = kDeviceStateStarting;
                TaskHandle_t activation_task_handle_ = nullptr;
                std::atomic<bool> activation_running_{false};
                DeviceState GetDeviceState() const { return state; }
                void SetDeviceState(DeviceState next) { state = next; }
                void ActivationTask() {}
                void HandleNetworkConnectedEvent();
            };
        '''
        checks = r'''
            int main(int argc, char** argv) {
                assert(argc == 2);
                const std::string scenario = argv[1];
                Application app;
                auto& board = Board::GetInstance();
                if (scenario == "stale-while-starting" || scenario == "stale-after-ap-start") {
                    // The notification was queued while connected, but manual AP startup
                    // or disconnection completed before the application processes its bit.
                    app.state = scenario == "stale-after-ap-start" ? kDeviceStateWifiConfiguring
                                                                   : kDeviceStateStarting;
                    const auto before = app.state;
                    board.connected = false;
                    app.HandleNetworkConnectedEvent();
                    assert(app.state == before && "stale Connected changed application state");
                    assert(task_creations == 0 && !app.activation_running_ &&
                           "stale Connected started activation while station is offline");
                } else if (scenario == "connected-startup") {
                    board.connected = true;
                    app.HandleNetworkConnectedEvent();
                    assert(app.state == kDeviceStateActivating);
                    assert(task_creations == 1 && app.activation_running_);
                } else {
                    assert(scenario == "connected-idle");
                    board.connected = true;
                    app.state = kDeviceStateIdle;
                    app.HandleNetworkConnectedEvent();
                    assert(app.state == kDeviceStateIdle && task_creations == 0);
                    assert(board.display.updates == 1);
                }
            }
        '''
        cls.directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.directory.cleanup)
        path = Path(cls.directory.name)
        driver = path / "air_network_state.cc"
        driver.write_text(textwrap.dedent(platform) + method + textwrap.dedent(checks))
        cls.executable = path / "air_network_state"
        compiled = subprocess.run(compiler + ["-std=c++23", "-I", str(ROOT / "main"),
                                              str(driver), "-o", str(cls.executable)],
                                  capture_output=True, text=True)
        if compiled.returncode:
            raise AssertionError(compiled.stdout + compiled.stderr)

    def scenario(self, name):
        result = subprocess.run([str(self.executable), name], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_stale_connected_does_not_activate_while_offline(self):
        self.scenario("stale-while-starting")

    def test_queued_connected_bit_does_not_activate_after_manual_ap_start(self):
        self.scenario("stale-after-ap-start")

    def test_current_connected_startup_still_activates(self):
        self.scenario("connected-startup")

    def test_current_connected_idle_preserves_its_state(self):
        self.scenario("connected-idle")
