"""Run the production AIR backlight adapter without the legacy timer platform."""

import os
import shlex
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class AirBrightnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shlex.split(os.environ.get("CXX", "c++"))
        if not compiler or shutil.which(compiler[0]) is None:
            raise unittest.SkipTest("requires a host C++23 compiler")
        source = (ROOT / "main/boards/custom/waveshare-air-monitor-1.8-v1/air_monitor_board.cc").read_text()
        start = source.index("class AirBacklight : public Backlight")
        brace = source.index("{", start)
        depth, end = 1, brace + 1
        while depth:
            depth += (source[end] == "{") - (source[end] == "}")
            end += 1
        adapter = source[start:end] + ";\n"
        platform = r'''
            #include <algorithm>
            #include <atomic>
            #include <cassert>
            #include <cstdint>
            #include <string>
            class Backlight {
            public:
                int legacy_transitions = 0;
                virtual void SetBrightness(uint8_t percent, bool = false) {
                    // Legacy requests start a timer; physical updates happen later.
                    target_brightness_ = percent;
                    ++legacy_transitions;
                }
                virtual uint8_t brightness() const { return brightness_; }
            protected:
                virtual void SetBrightnessImpl(uint8_t) = 0;
                uint8_t brightness_ = 0, target_brightness_ = 0;
            };
            namespace air {
            struct AirDisplay {
                std::atomic<int> physical{-1}, user{-1};
                int physical_requests = 0, user_requests = 0;
                void RequestBrightness(uint8_t value) { physical = value; ++physical_requests; }
                void RequestUserBrightness(uint8_t value) { user = value; ++user_requests; }
            };
            }
        '''
        checks = r'''
            int main(int argc, char** argv) {
                assert(argc == 2);
                const std::string scenario = argv[1];
                air::AirDisplay display;
                AirBacklight adapter(display);
                Backlight* backlight = &adapter;
                if (scenario == "direct") {
                    backlight->SetBrightness(73);
                    assert(backlight->legacy_transitions == 0 && "AIR must not start legacy timer fades");
                    assert(display.physical == 73 && display.physical_requests == 1 &&
                           "ordinary brightness must directly reach the display mailbox");
                    assert(backlight->brightness() == 73 && "base-pointer getter must reflect the applied request");
                    assert(display.user_requests == 0);
                } else if (scenario == "clamp") {
                    backlight->SetBrightness(0);
                    assert(display.physical == 1 && backlight->brightness() == 1 &&
                           "AIR brightness zero must clamp to one");
                    backlight->SetBrightness(255);
                    assert(display.physical == 100 && backlight->brightness() == 100 &&
                           "AIR brightness must clamp to one hundred");
                    assert(backlight->legacy_transitions == 0 && display.physical_requests == 2);
                } else {
                    assert(scenario == "permanent");
                    backlight->SetBrightness(37);
                    backlight->SetBrightness(0, true);
                    assert(display.user == 1 && display.user_requests == 1 &&
                           "permanent brightness must enqueue a clamped user preference");
                    assert(display.physical == 37 && display.physical_requests == 1 &&
                           backlight->brightness() == 37 && "pending user intent must not bypass LVGL preference application");
                    backlight->SetBrightness(255, true);
                    assert(display.user == 100 && display.user_requests == 2 && display.physical == 37);
                    // The LVGL task consumes the preference and applies the regular request.
                    backlight->SetBrightness(static_cast<uint8_t>(display.user.load()));
                    assert(display.physical == 100 && display.physical_requests == 2 &&
                           backlight->brightness() == 100 && backlight->legacy_transitions == 0);
                }
            }
        '''
        cls.directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.directory.cleanup)
        path = Path(cls.directory.name)
        driver = path / "air_brightness.cc"
        cls.executable = path / "air_brightness"
        driver.write_text(textwrap.dedent(platform) + adapter + textwrap.dedent(checks))
        compiled = subprocess.run(compiler + ["-std=c++23", str(driver), "-o", str(cls.executable)],
                                  capture_output=True, text=True)
        if compiled.returncode:
            raise AssertionError(compiled.stdout + compiled.stderr)

    def run_scenario(self, scenario):
        result = subprocess.run([str(self.executable), scenario], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_regular_request_updates_mailbox_and_virtual_getter_without_timer(self):
        self.run_scenario("direct")

    def test_regular_request_clamps_brightness_to_one_through_one_hundred(self):
        self.run_scenario("clamp")

    def test_permanent_request_waits_for_lvgl_preference_application(self):
        self.run_scenario("permanent")
