"""Exercise the AIR codec adapter with fake ES8311 and persistent settings."""

import os
import shlex
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
HEADER = ROOT / "main/boards/custom/waveshare-air-monitor-1.8-v1/air_audio_codec.h"


class AirAudioCodecTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shlex.split(os.environ.get("CXX", "c++"))
        if not compiler or shutil.which(compiler[0]) is None:
            raise unittest.SkipTest("requires a host C++23 compiler")
        cls.directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.directory.cleanup)
        path = Path(cls.directory.name)
        (path / "audio/codecs").mkdir(parents=True)
        (path / "settings.h").write_text(textwrap.dedent(r'''
            #pragma once
            #include <cassert>
            #include <map>
            #include <string>
            inline std::map<std::string, int> persisted;
            inline int writes = 0;
            struct Settings {
                bool writable;
                Settings(const char* ns, bool write = false) : writable(write) {
                    assert(std::string(ns) == "audio");
                }
                int GetInt(const char* key, int fallback = 0) {
                    const auto it = persisted.find(key);
                    return it == persisted.end() ? fallback : it->second;
                }
                void SetInt(const char* key, int value) {
                    assert(writable);
                    ++writes;
                    persisted[key] = value;
                }
            };
        '''))
        (path / "audio/codecs/es8311_audio_codec.h").write_text(textwrap.dedent(r'''
            #pragma once
            #include "settings.h"
            struct Es8311AudioCodec {
                int forwarded_pin, base_starts = 0, hardware_volume = -1;
                explicit Es8311AudioCodec(int pin) : forwarded_pin(pin) {}
                virtual ~Es8311AudioCodec() = default;
                virtual void Start() {
                    ++base_starts;
                    Settings settings("audio", false);
                    output_volume_ = settings.GetInt("output_volume", output_volume_);
                    if (output_volume_ <= 0) output_volume_ = 10;
                }
                virtual void SetOutputVolume(int volume) {
                    // The real implementation updates hardware then persists the value.
                    hardware_volume = volume;
                    output_volume_ = volume;
                    Settings settings("audio", true);
                    settings.SetInt("output_volume", volume);
                }
                int output_volume() const { return output_volume_; }
            protected:
                int output_volume_ = 70;
            };
        '''))
        # With no AIR adapter, preserve the upstream behavior to demonstrate the
        # restart regression through the same runtime assertion used after fixing it.
        legacy = textwrap.dedent(r'''
            #include <functional>
            #include "audio/codecs/es8311_audio_codec.h"
            namespace air {
            struct AirAudioCodec : Es8311AudioCodec {
                AirAudioCodec(std::function<void(int)>, int pin) : Es8311AudioCodec(pin) {}
            };
            }
        ''')
        cls.checks = textwrap.dedent(r'''
            #include <atomic>
            #include <cassert>
            #include <string>
            int main(int argc, char** argv) {
                assert(argc == 2);
                const std::string scenario = argv[1];
                std::atomic<int> observed{-1};
                int notifications = 0;
                auto observer = [&](int value) {
                    assert(writes == 0 || persisted.at("output_volume") == value);
                    observed = value;
                    ++notifications;
                };
                if (scenario == "restart-mute") {
                    persisted["output_volume"] = 0;
                    air::AirAudioCodec codec(observer, 7);
                    codec.Start();
                    assert(codec.output_volume() == 0 && "persisted mute must survive restart");
                    assert(observed == 0 && notifications == 1);
                    assert(writes == 0 && persisted.at("output_volume") == 0);
                    assert(codec.base_starts == 1 && codec.forwarded_pin == 7);
                } else if (scenario == "defaults") {
                    air::AirAudioCodec codec(observer, 7);
                    codec.Start();
                    assert(codec.output_volume() == 70 && observed == 70);
                    assert(writes == 0 && persisted.empty());
                } else if (scenario == "startup-clamp") {
                    for (int stored : {-7, 176}) {
                        persisted["output_volume"] = stored;
                        air::AirAudioCodec codec(observer, 7);
                        codec.Start();
                        const int expected = stored < 0 ? 0 : 100;
                        assert(codec.output_volume() == expected && observed == expected);
                        assert(writes == 0 && persisted.at("output_volume") == stored &&
                               "startup must not rewrite retained NVS");
                    }
                } else if (scenario == "set-and-restart") {
                    air::AirAudioCodec codec(observer, 7);
                    Es8311AudioCodec* base = &codec;
                    base->Start();
                    for (int requested : {-9, 0, 37, 100, 141}) {
                        const int expected = requested < 0 ? 0 : requested > 100 ? 100 : requested;
                        const int before = notifications;
                        base->SetOutputVolume(requested);
                        assert(codec.hardware_volume == expected && codec.output_volume() == expected);
                        assert(observed == expected && notifications == before + 1 &&
                               "every local or MCP change must publish after the base setter");
                        assert(persisted.at("output_volume") == expected);
                    }
                    assert(writes == 5 && "one release must cause only one persistent update");
                    air::AirAudioCodec rebooted(observer, 7);
                    rebooted.Start();
                    assert(rebooted.output_volume() == 100 && observed == 100 && writes == 5);
                } else {
                    assert(scenario == "optional-observer");
                    air::AirAudioCodec codec({}, 7);
                    codec.Start();
                    codec.SetOutputVolume(0);
                    assert(codec.output_volume() == 0 && persisted.at("output_volume") == 0);
                }
            }
        ''')
        cls.executables = {}
        for name, definition in (("production", f'#include "{HEADER}"\n' if HEADER.is_file() else legacy),
                                 ("legacy", legacy)):
            driver = path / (name + ".cc")
            executable = path / name
            driver.write_text(definition + cls.checks)
            result = subprocess.run(compiler + ["-std=c++23", "-Wall", "-Wextra", "-Werror", "-I", str(path),
                                               str(driver), "-o", str(executable)],
                                    capture_output=True, text=True)
            if result.returncode:
                raise AssertionError(result.stdout + result.stderr)
            cls.executables[name] = executable

    def run_scenario(self, scenario, variant="production"):
        result = subprocess.run([str(self.executables[variant]), scenario], capture_output=True, text=True)
        return result

    def test_persisted_zero_remains_muted_without_rewriting_nvs(self):
        result = self.run_scenario("restart-mute")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_unconfigured_volume_keeps_default_without_creating_nvs(self):
        result = self.run_scenario("defaults")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_invalid_saved_values_are_clamped_without_rewriting_nvs(self):
        result = self.run_scenario("startup-clamp")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_virtual_setter_clamps_persists_and_publishes_local_or_mcp_changes(self):
        result = self.run_scenario("set-and-restart")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_empty_observer_is_valid(self):
        result = self.run_scenario("optional-observer")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_unadapted_es8311_would_lose_persisted_mute(self):
        result = self.run_scenario("restart-mute", "legacy")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("persisted mute must survive restart", result.stderr)
