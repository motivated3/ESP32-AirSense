"""Execute the real final preference snapshot and check two guard mutations."""

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


class AirPreferencesFlushTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.compiler = shlex.split(os.environ.get("CXX", "c++"))
        if not cls.compiler or shutil.which(cls.compiler[0]) is None:
            raise unittest.SkipTest("requires a host C++23 compiler")
        source = (ROOT / "main/boards/custom/waveshare-air-monitor-1.8-v1/air_display.cc").read_text(
            encoding="utf-8")
        cls.methods = "\n".join(definition(source, signature) for signature in (
            "bool AirDisplay::CommitPreferences(", "bool AirDisplay::FlushPreferences()"))
        cls.platform = textwrap.dedent(r'''
            #include <atomic>
            #include <cassert>
            #include <cstdint>
            #include <functional>
            #include <map>
            #include <string>
            #include "air_ui_state.h"
            #include "air_solar_theme.h"
            bool lock_available = true, lock_held = false, storage_available = true;
            int lock_attempts = 0, unlocks = 0, commits = 0;
            std::function<void()> on_unlock;
            std::map<std::string, int> persisted;
            bool lvgl_port_lock(int timeout) {
                assert(timeout == 50 && !lock_held);
                ++lock_attempts;
                lock_held = lock_available;
                return lock_held;
            }
            void lvgl_port_unlock() {
                assert(lock_held && "snapshot must hold the LVGL lock");
                lock_held = false;
                ++unlocks;
                if (on_unlock) on_unlock();
            }
            struct StorageResult { bool available; };
            StorageResult GetStorageInitResult() { return {storage_available}; }
            struct Settings {
                std::map<std::string, int> values;
                Settings(const char* space, bool writable) {
                    assert(std::string(space) == "air" && writable && !lock_held);
                    assert(storage_available && "unavailable NVS must not be opened");
                }
                ~Settings() { ++commits; persisted = values; }
                void SetBool(const char* key, bool value) { values[key] = value; }
                void SetInt(const char* key, int value) { values[key] = value; }
            };
            namespace air {
            struct State {
                bool night_value = true, reduce_motion = true, voice_enabled = false;
                int day = 86, dim = 12;
                struct Alerts {
                    bool co2_enabled = false, hcho_enabled = true, sound = false;
                    int co2_ppm = 2100, hcho_ppb = 120;
                } alerts;
                ThemeMode theme_mode() const { assert(lock_held); return ThemeMode::Auto; }
                bool night() const { assert(lock_held); return night_value; }
                int day_brightness() const { assert(lock_held); return day; }
                int night_brightness() const { assert(lock_held); return dim; }
            };
            struct AirDisplay {
                State state_;
                SolarThemeClock solar_clock_;
                AirDisplay() { solar_clock_.SetLocation({39904000, 116407000}); }
                std::atomic<uint32_t> preferences_generation_{0}, saved_generation_{0};
                bool CommitPreferences(bool force);
                bool FlushPreferences();
            };
        ''')
        cls.checks = textwrap.dedent(r'''
            } // namespace air
            int main(int argc, char** argv) {
                assert(argc == 2);
                const std::string scenario = argv[1];
                air::AirDisplay display;
                if (scenario == "unreleased-slider") {
                    // A slider value can change before RELEASED increments its generation.
                    assert(display.preferences_generation_ == display.saved_generation_);
                    assert(display.FlushPreferences());
                    assert(commits == 1 && persisted.at("day") == 86 &&
                           "final flush must capture a slider value before release");
                    assert(persisted.contains("co2_limit") && persisted.at("co2_limit") == 2100 &&
                           "final flush must capture the unreleased alert threshold");
                } else if (scenario == "one-snapshot") {
                    display.preferences_generation_ = 7;
                    on_unlock = [&display]() {
                        display.state_ = {false, false, true, 24, 3};
                        display.state_.alerts = {true, false, true, 3200, 200};
                        display.solar_clock_.SetLocation({0, 0});
                        display.preferences_generation_ = 8;
                    };
                    assert(display.FlushPreferences());
                    const std::map<std::string, int> expected = {
                        {"theme_mode", 2}, {"solar_lat", 39904000}, {"solar_lon", 116407000},
                        {"night", 1}, {"reduce_motion", 1}, {"voice", 0}, {"day", 86}, {"night_level", 12},
                        {"alert_co2", 0}, {"alert_hcho", 1}, {"alert_sound", 0},
                        {"co2_limit", 2100}, {"hcho_limit", 120}};
                    assert(commits == 1 && persisted == expected &&
                           "all preferences must come from one locked snapshot");
                    assert(display.saved_generation_ == 7 && display.preferences_generation_ == 8);
                    assert(lock_attempts == 1 && unlocks == 1);
                } else if (scenario == "lock-failure") {
                    display.preferences_generation_ = 3;
                    display.saved_generation_ = 1;
                    lock_available = false;
                    assert(!display.FlushPreferences() && "lock failure must not report a completed flush");
                    assert(commits == 0 && display.saved_generation_ == 1 && unlocks == 0);
                } else if (scenario == "nvs-unavailable") {
                    storage_available = false;
                    display.preferences_generation_ = 3;
                    // Saving cannot recover failed NVS; shutdown is permitted to continue.
                    assert(display.FlushPreferences());
                    assert(commits == 0 && persisted.empty());
                    assert(display.saved_generation_ == 3 && lock_attempts == 1 && unlocks == 1);
                } else {
                    assert(scenario == "clean-normal-save");
                    assert(display.CommitPreferences(false));
                    assert(commits == 0 && lock_attempts == 0);
                }
            }
        ''')
        cls.directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.directory.cleanup)
        cls.executables = {}
        cls.compile_variant("production", cls.methods)

    @classmethod
    def compile_variant(cls, name, methods):
        if name not in cls.executables:
            path = Path(cls.directory.name)
            driver = path / f"{name}.cc"
            executable = path / name
            driver.write_text(cls.platform + methods + cls.checks, encoding="utf-8")
            result = subprocess.run(cls.compiler + ["-std=c++23", "-I" + str(ROOT / "main/boards/custom/waveshare-air-monitor-1.8-v1"), "-I" + str(ROOT / "main"), str(driver), "-o", str(executable)],
                                    capture_output=True, text=True)
            if result.returncode:
                raise AssertionError(result.stdout + result.stderr)
            cls.executables[name] = executable
        return cls.executables[name]

    def run_scenario(self, scenario, variant="production"):
        return subprocess.run([str(self.executables[variant]), scenario], capture_output=True, text=True)

    def assert_scenario_passes(self, scenario):
        result = self.run_scenario(scenario)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_final_flush_captures_unreleased_slider(self):
        self.assert_scenario_passes("unreleased-slider")

    def test_all_preferences_share_one_snapshot_and_commit(self):
        self.assert_scenario_passes("one-snapshot")

    def test_lock_failure_does_not_report_completion(self):
        self.assert_scenario_passes("lock-failure")

    def test_unavailable_nvs_is_not_written(self):
        self.assert_scenario_passes("nvs-unavailable")

    def test_normal_clean_save_does_not_write_again(self):
        self.assert_scenario_passes("clean-normal-save")

    def test_force_guard_mutation_is_detected(self):
        mutated = self.methods.replace("return CommitPreferences(true);", "return CommitPreferences(false);")
        self.assertNotEqual(mutated, self.methods, "production force call must be identified")
        self.compile_variant("no-force", mutated)
        result = self.run_scenario("unreleased-slider", "no-force")
        self.assertNotEqual(result.returncode, 0, "force mutation must fail the runtime regression")
        self.assertIn("final flush must capture", result.stderr)

    def test_lock_guard_mutation_is_detected(self):
        mutated = self.methods.replace("if (!lvgl_port_lock(50))\n        return false;", "")
        self.assertNotEqual(mutated, self.methods, "production lock guard must be identified")
        self.compile_variant("no-lock", mutated)
        result = self.run_scenario("lock-failure", "no-lock")
        self.assertNotEqual(result.returncode, 0, "lock mutation must fail the runtime regression")
        self.assertIn("lock_held", result.stderr)
