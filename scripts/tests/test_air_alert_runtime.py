"""Execute production alert delivery against a controlled screen and task queue."""

import os
import shlex
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
AIR = ROOT / "main/boards/custom/waveshare-air-monitor-1.8-v1"


def definition(source, signature):
    start = source.index(signature)
    brace = source.index("{", start)
    depth, end = 1, brace + 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end]


class AirAlertRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.compiler = shlex.split(os.environ.get("CXX", "c++"))
        if not cls.compiler or shutil.which(cls.compiler[0]) is None:
            raise unittest.SkipTest("requires a host C++23 compiler")
        source = (AIR / "air_display.cc").read_text(encoding="utf-8")
        header = (AIR / "air_display.h").read_text(encoding="utf-8")
        board = (AIR / "air_monitor_board.cc").read_text(encoding="utf-8")
        sound_check = definition(header, "bool CanSoundAlert(").replace(
            "bool CanSoundAlert(", "bool AirDisplay::CanSoundAlert(", 1)
        cls.methods = "\n".join((
            sound_check,
            definition(source, "void AirDisplay::UpdateAlerts("),
            "void AirDisplay::InstallCallbacks() {\n",
            definition(source, "callbacks_.acknowledge_alert =") + ";",
            definition(source, "callbacks_.alerts_changed =") + ";\n}",
        ))
        cls.board_callback = definition(board, "callbacks.alert_sound =") + ";"
        cls.platform = textwrap.dedent(r'''
            #include <atomic>
            #include <cassert>
            #include <cstdint>
            #include <deque>
            #include <functional>
            #include <memory>
            #include <string>
            #include <utility>
            #include "air_alert_policy.h"
            #include "air_model.h"
            #include "air_ui_state.h"
            #include "device_state.h"

            bool application_task = false;
            struct AudioService { int attempted = 0; };
            struct Application {
                std::deque<std::function<void()>> tasks;
                DeviceState state = kDeviceStateIdle;
                AudioService audio;
                static Application& GetInstance() { static Application app; return app; }
                void Schedule(std::function<void()>&& callback) {
                    assert(!application_task && "GUI must only enqueue alert audio");
                    tasks.push_back(std::move(callback));
                }
                DeviceState GetDeviceState() const { return state; }
                AudioService& GetAudioService() { return audio; }
                void RunNext() {
                    assert(!application_task && !tasks.empty());
                    auto callback = std::move(tasks.front());
                    tasks.pop_front();
                    application_task = true;
                    callback();
                    application_task = false;
                }
            };
            namespace air {
            // The real Ogg/queue helper has its own parser test; observe its entry here.
            bool TryPlayAirAlertTone(AudioService& audio) {
                assert(application_task && "audio entry must run on the application task");
                ++audio.attempted;
                return true;
            }
            struct AirViewCallbacks {
                std::function<void(uint32_t)> acknowledge_alert, alert_sound;
                std::function<void()> alerts_changed;
            };
            struct VisibleView {
                AirUiState& state;
                AlertSnapshot alerts;
                bool visible = false;
                explicit VisibleView(AirUiState& value) : state(value) {}
                void SetAlerts(const AlertSnapshot& value, const AirSnapshot&,
                               const PowerSnapshot& power) {
                    alerts = value;
                    (void)power;
                    visible = false; // The production view no longer creates a concentration overlay.
                }
                bool AlertVisible() const { return visible; }
            };
            struct AirDisplay {
                AirUiState state_;
                AirAlertPolicy alert_policy_;
                AirViewCallbacks callbacks_;
                std::unique_ptr<VisibleView> view_ = std::make_unique<VisibleView>(state_);
                std::atomic<bool> requested_on_{true};
                uint64_t next_alert_refresh_ = 0;
                uint32_t wake_alert_generation_ = 0, sounded_alert_generation_ = 0;
                std::atomic<uint32_t> alert_sound_token_{0};
                AirDisplay() { InstallCallbacks(); }
                void InstallCallbacks();
                void UpdateAlerts(const AirSnapshot& sample, const PowerSnapshot& power);
                bool CanSoundAlert(uint32_t generation) const;
            };
        ''')
        cls.board_platform = textwrap.dedent(r'''
            } // namespace air
            struct Hardware {
                bool shutting_down = false;
                bool IsShuttingDown() const { return shutting_down; }
            };
            struct Codec {
                int volume = 47;
                int output_volume() const { return volume; }
            };
            struct Board {
                Hardware hardware_;
                Codec codec;
                air::AirDisplay* display_;
                explicit Board(air::AirDisplay& display) : display_(&display) {}
                Codec* GetAudioCodec() { return &codec; }
                void InstallCallbacks(air::AirViewCallbacks& callbacks) {
        ''')
        cls.checks = textwrap.dedent(r'''
                }
            };
            struct Fixture {
                air::AirModel model;
                air::AirDisplay display;
                Board board{display};
                air::PowerSnapshot power;
                Fixture() { board.InstallCallbacks(display.callbacks_); }
                void Tick(uint64_t now) { display.UpdateAlerts(model.Snapshot(now), power); }
                void HighCo2(uint64_t start, uint64_t end) {
                    for (uint64_t now = start; now <= end; now += 5000) {
                        model.ApplyScd41({1600, 25, 50}, now);
                        Tick(now);
                    }
                }
                void Screen(bool on) {
                    display.requested_on_ = on;
                    display.state_.SetDisplayOn(on);
                    power.display_on = on;
                }
            };
            int main(int argc, char** argv) {
                assert(argc == 2);
                const std::string scenario = argv[1];
                Fixture f;
                auto& app = Application::GetInstance();
                if (scenario == "screen-off-once") {
                    f.Screen(false);
                    f.HighCo2(0, 30000);
                    assert(!f.display.requested_on_ && "concentration must not wake the display");
                    assert(!f.display.view_->AlertVisible() && app.tasks.size() == 1);
                    app.RunNext();
                    assert(app.audio.attempted == 1);
                    f.HighCo2(35000, 60000);
                    assert(!f.display.requested_on_ && app.tasks.empty());
                    f.Screen(true);
                    f.Tick(60001);
                    assert(app.tasks.empty() && "waking must not replay a consumed cue");
                } else if (scenario == "visible-once") {
                    f.HighCo2(0, 30000);
                    assert(app.tasks.size() == 1 && f.display.CanSoundAlert(1));
                    app.RunNext();
                    f.HighCo2(35000, 60000);
                    for (uint64_t now = 60001; now < 65000; now += 100) f.Tick(now);
                    assert(app.tasks.empty() && app.audio.attempted == 1 &&
                           "same generation must not sound twice");
                } else if (scenario == "sound-disabled") {
                    f.display.state_.alerts.sound = false;
                    f.HighCo2(0, 30000);
                    assert(!f.display.view_->AlertVisible() && f.display.view_->alerts.active);
                    assert(!f.display.CanSoundAlert(1) && app.tasks.empty());
                    f.display.state_.alerts.sound = true;
                    f.Tick(30001);
                    assert(app.tasks.empty() && "reenabling sound must not replay this event");
                } else if (scenario == "acknowledge-queued") {
                    f.HighCo2(0, 30000);
                    assert(app.tasks.size() == 1 && f.display.CanSoundAlert(1));
                    f.display.callbacks_.acknowledge_alert(0);
                    assert(f.display.CanSoundAlert(1) && "stale acknowledgement must be ignored");
                    f.display.callbacks_.acknowledge_alert(1);
                    assert(!f.display.CanSoundAlert(1) && !f.display.CanSoundAlert(0));
                    app.RunNext();
                    assert(app.audio.attempted == 0 && "acknowledgement must cancel queued audio");
                    f.Tick(30001);
                    assert(!f.display.view_->AlertVisible() && app.tasks.empty());
                } else if (scenario == "shutdown-before-event") {
                    f.Screen(false);
                    f.board.hardware_.shutting_down = f.power.shutting_down = true;
                    f.HighCo2(0, 30000);
                    assert(!f.display.requested_on_ && !f.display.CanSoundAlert(1));
                    assert(f.display.view_->alerts.pending == 0 && app.tasks.empty());
                } else if (scenario == "shutdown-clears-token") {
                    f.HighCo2(0, 30000);
                    assert(f.display.CanSoundAlert(1) && app.tasks.size() == 1);
                    f.power.shutting_down = true;
                    f.Tick(30001);
                    assert(!f.display.CanSoundAlert(1) && !f.display.view_->AlertVisible());
                    app.RunNext();
                    assert(app.audio.attempted == 0);
                } else if (scenario == "sound-setting-cancels-queued") {
                    f.HighCo2(0, 30000);
                    assert(app.tasks.size() == 1);
                    f.display.state_.alerts.sound = false;
                    f.display.callbacks_.alerts_changed();
                    assert(!f.display.CanSoundAlert(1));
                    app.RunNext();
                    assert(app.audio.attempted == 0);
                } else if (scenario == "board-muted" || scenario == "board-busy" ||
                           scenario == "board-shutdown" || scenario == "voice-disabled") {
                    f.display.state_.voice_enabled = false;
                    f.HighCo2(0, 30000);
                    assert(app.tasks.size() == 1 && f.display.CanSoundAlert(1));
                    if (scenario == "board-muted") f.board.codec.volume = 0;
                    if (scenario == "board-busy") app.state = kDeviceStateSpeaking;
                    if (scenario == "board-shutdown") f.board.hardware_.shutting_down = true;
                    app.RunNext();
                    assert(app.audio.attempted == (scenario == "voice-disabled" ? 1 : 0));
                    f.board.codec.volume = 47;
                    app.state = kDeviceStateIdle;
                    f.board.hardware_.shutting_down = false;
                    f.Tick(30001);
                    assert(app.tasks.empty() && "a skipped cue must not be queued later");
                } else {
                    assert(scenario == "old-generation");
                    f.HighCo2(0, 30000);  // Keep the generation-1 audio callback queued.
                    for (uint64_t now = 31000; now <= 61000; now += 1000) {
                        f.model.ApplySfa40({90, 25, 50, true, true, 0}, now);
                        if (now % 5000 == 0) f.model.ApplyScd41({1600, 25, 50}, now);
                        f.Tick(now);
                    }
                    assert(f.display.CanSoundAlert(2) && !f.display.CanSoundAlert(1));
                    assert(app.tasks.size() == 2);
                    app.RunNext();
                    assert(app.audio.attempted == 0 && "old generation must not play delayed audio");
                    app.RunNext();
                    assert(app.audio.attempted == 1 && app.tasks.empty());
                }
            }
        ''')
        cls.directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.directory.cleanup)
        cls.executables = {}
        cls.compile_variant("production", cls.methods)

    @classmethod
    def compile_variant(cls, name, methods):
        if name in cls.executables:
            return
        path = Path(cls.directory.name)
        driver, executable = path / (name + ".cc"), path / name
        driver.write_text(cls.platform + methods + cls.board_platform +
                          cls.board_callback + cls.checks, encoding="utf-8")
        result = subprocess.run(
            cls.compiler + ["-std=c++23", "-Wall", "-Wextra", "-Werror", f"-I{AIR}",
                            f"-I{ROOT / 'main'}", str(driver), str(AIR / "air_alert_policy.cc"),
                            str(AIR / "air_model.cc"), "-o", str(executable)],
            capture_output=True, text=True, timeout=60)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)
        cls.executables[name] = executable

    def run_scenario(self, scenario, variant="production"):
        return subprocess.run([str(self.executables[variant]), scenario],
                              capture_output=True, text=True, timeout=10,
                              cwd=self.directory.name)

    def check_scenario(self, scenario):
        result = self.run_scenario(scenario)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_sleeping_event_keeps_screen_off_and_sounds_once_without_overlay(self):
        self.check_scenario("screen-off-once")

    def test_persistent_visible_event_sounds_once_across_new_samples_and_ticks(self):
        self.check_scenario("visible-once")

    def test_sound_disabled_preserves_home_alert_state_without_later_replay(self):
        self.check_scenario("sound-disabled")

    def test_acknowledgement_invalidates_queued_sound_immediately(self):
        self.check_scenario("acknowledge-queued")

    def test_shutdown_suppresses_new_wake_and_audio(self):
        self.check_scenario("shutdown-before-event")

    def test_shutdown_clears_existing_token_and_overlay(self):
        self.check_scenario("shutdown-clears-token")

    def test_sound_setting_change_cancels_audio_already_queued(self):
        self.check_scenario("sound-setting-cancels-queued")

    def test_muted_codec_skips_audio_without_later_retry(self):
        self.check_scenario("board-muted")

    def test_busy_application_skips_audio_without_later_retry(self):
        self.check_scenario("board-busy")

    def test_board_shutdown_is_rechecked_when_queued_callback_executes(self):
        self.check_scenario("board-shutdown")

    def test_voice_disabled_does_not_disable_independent_alert_sound(self):
        self.check_scenario("voice-disabled")

    def test_older_generation_audio_cannot_play_after_a_later_event(self):
        self.check_scenario("old-generation")

    def test_removing_sound_generation_gate_causes_repeated_cues(self):
        mutated = self.methods.replace("alerts.generation != sounded_alert_generation_", "true")
        self.assertNotEqual(mutated, self.methods, "sound generation gate must be identified")
        self.compile_variant("no-sound-generation", mutated)
        result = self.run_scenario("visible-once", "no-sound-generation")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("same generation must not sound twice", result.stderr)


if __name__ == "__main__":
    unittest.main()
