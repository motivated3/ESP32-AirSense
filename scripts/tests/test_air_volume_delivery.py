"""Execute real AIR volume delivery methods across a controlled task queue."""

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


class AirVolumeDeliveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.compiler = shlex.split(os.environ.get("CXX", "c++"))
        if not cls.compiler or shutil.which(cls.compiler[0]) is None:
            raise unittest.SkipTest("requires a host C++23 compiler")
        source = (AIR / "air_display.cc").read_text(encoding="utf-8")
        header = (AIR / "air_display.h").read_text(encoding="utf-8")
        request = definition(header, "void RequestVolume(").replace(
            "void RequestVolume(", "void AirDisplay::RequestVolume(", 1)
        cls.methods = "\n".join((request, definition(source, "void AirDisplay::QueueVolume("),
                                  definition(source, "int AirDisplay::DisplayVolume() const")))
        cls.platform = textwrap.dedent(r'''
            #include <atomic>
            #include <cassert>
            #include <cstdint>
            #include <deque>
            #include <functional>
            #include <string>
            #include <utility>
            bool application_task = false;
            struct Application {
                std::deque<std::function<void()>> tasks;
                static Application& GetInstance() { static Application app; return app; }
                void Schedule(std::function<void()>&& callback) {
                    assert(!application_task && "the GUI must only enqueue volume work");
                    tasks.push_back(std::move(callback));
                }
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
            struct AirDisplay {
                std::atomic<int> volume_{-1}, user_volume_{70};
                std::atomic<uint32_t> volume_generation_{0}, applied_volume_generation_{0};
                void RequestVolume(int percent);
                void QueueVolume(int value, std::function<void(int)> apply);
                int DisplayVolume() const;
            };
        ''')
        cls.checks = textwrap.dedent(r'''
            } // namespace air
            int main(int argc, char** argv) {
                assert(argc == 2);
                const std::string scenario = argv[1];
                air::AirDisplay display;
                display.RequestVolume(70);
                auto& app = Application::GetInstance();
                int writes = 0;
                auto apply = [&](int volume) {
                    assert(application_task && "codec and NVS must run on the application task");
                    ++writes;
                    // The real codec observer publishes only this atomic mailbox.
                    display.RequestVolume(volume);
                };
                if (scenario == "deferred") {
                    display.QueueVolume(37, apply);
                    assert(writes == 0 && app.tasks.size() == 1);
                    assert(display.DisplayVolume() == 37 && "pending request must render immediately");
                    assert(display.volume_ == 70 && "GUI must not write the actual codec snapshot");
                    app.RunNext();
                    assert(writes == 1 && app.tasks.empty() && display.DisplayVolume() == 37);
                    assert(display.volume_generation_ == display.applied_volume_generation_);
                } else if (scenario == "aba") {
                    display.QueueVolume(20, apply);
                    display.QueueVolume(40, apply);
                    display.QueueVolume(20, apply);
                    assert(writes == 0 && app.tasks.size() == 3);
                    app.RunNext();
                    assert(writes == 1 && display.volume_ == 20 && display.DisplayVolume() == 20);
                    app.RunNext();
                    assert(writes == 2 && display.volume_ == 40);
                    assert(display.DisplayVolume() == 20 &&
                           "older completion must not pull the latest slider request backwards");
                    app.RunNext();
                    assert(writes == 3 && app.tasks.empty() && display.DisplayVolume() == 20);
                    display.RequestVolume(63); // A later voice/MCP change is now authoritative.
                    assert(display.DisplayVolume() == 63 && "completed local intent must not mask MCP");
                } else {
                    assert(scenario == "external-pending");
                    display.QueueVolume(0, apply);
                    display.RequestVolume(80); // An already-running older MCP request completes.
                    assert(display.DisplayVolume() == 0 && writes == 0);
                    app.RunNext();
                    assert(display.DisplayVolume() == 0 && writes == 1);
                    display.RequestVolume(29);
                    assert(display.DisplayVolume() == 29 && app.tasks.empty());
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
            driver, executable = path / (name + ".cc"), path / name
            driver.write_text(cls.platform + methods + cls.checks, encoding="utf-8")
            result = subprocess.run(cls.compiler + ["-std=c++23", "-Wall", "-Wextra", "-Werror",
                                                    str(driver), "-o", str(executable)],
                                    capture_output=True, text=True)
            if result.returncode:
                raise AssertionError(result.stdout + result.stderr)
            cls.executables[name] = executable

    def run_scenario(self, scenario, variant="production"):
        return subprocess.run([str(self.executables[variant]), scenario], capture_output=True, text=True)

    def test_codec_work_is_deferred_with_immediate_pending_feedback(self):
        result = self.run_scenario("deferred")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_repeated_values_keep_latest_intent_until_its_own_completion(self):
        result = self.run_scenario("aba")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_older_mcp_completion_cannot_override_pending_local_mute(self):
        result = self.run_scenario("external-pending")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_removing_pending_selection_detects_intermediate_rebound(self):
        original = "return volume_generation_ == applied_volume_generation_ ? volume_.load() : user_volume_.load();"
        mutated = self.methods.replace(original, "return volume_.load();")
        self.assertNotEqual(mutated, self.methods, "production pending selection must be identified")
        self.compile_variant("no-pending", mutated)
        result = self.run_scenario("aba", "no-pending")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("older completion must not pull", result.stderr)
