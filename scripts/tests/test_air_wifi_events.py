"""Run the generated vendor NotifyEvent and production AIR mailbox on host threads."""

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
VENDOR = ROOT / "managed_components/78__esp-wifi-connect/wifi_manager.cc"
GENERATOR = ROOT / "scripts/generate_air_wifi_override.py"


def definition(source, signature):
    start = source.index(signature)
    brace = source.index("{", start)
    depth, end = 1, brace + 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end]


PLATFORM = r'''
    #include <array>
    #include <atomic>
    #include <cassert>
    #include <chrono>
    #include <condition_variable>
    #include <cstdlib>
    #include <functional>
    #include <iostream>
    #include <memory>
    #include <mutex>
    #include <string>
    #include <thread>
    #include <vector>
    #include "wifi_manager.h"
    #include "freertos/task.h"
    using namespace std::chrono_literals;
    struct TaskStopped {};
    struct FakeTask {
        std::mutex mutex;
        std::condition_variable wake;
        unsigned notifications = 0;
        bool stop = false;
        std::thread thread;
    };
    thread_local FakeTask* current_task = nullptr;
    std::vector<std::unique_ptr<FakeTask>> fake_tasks;
    std::atomic<int> fail_creations{0};
    bool delay_creation = false;
    int xTaskCreate(void (*run)(void*), const char*, unsigned, void* context,
                    unsigned, TaskHandle_t* handle) {
        if (fail_creations.load() > 0) {
            --fail_creations;
            return 0;
        }
        if (delay_creation) std::this_thread::sleep_for(20ms);
        auto task = std::make_unique<FakeTask>();
        *handle = task.get();
        auto* raw = task.get();
        fake_tasks.push_back(std::move(task));
        raw->thread = std::thread([run, context, raw]() {
            current_task = raw;
            try { run(context); } catch (const TaskStopped&) {}
        });
        return pdPASS;
    }
    void xTaskNotifyGive(TaskHandle_t task) {
        std::lock_guard<std::mutex> lock(task->mutex);
        ++task->notifications;
        task->wake.notify_all();
    }
    unsigned ulTaskNotifyTake(int clear, unsigned) {
        std::unique_lock<std::mutex> lock(current_task->mutex);
        current_task->wake.wait(lock, []() {
            return current_task->stop || current_task->notifications;
        });
        if (current_task->stop) throw TaskStopped{};
        const auto count = current_task->notifications;
        if (clear) current_task->notifications = 0;
        else --current_task->notifications;
        return count;
    }
    void StopFakeTasks() {
        for (auto& task : fake_tasks) {
            std::lock_guard<std::mutex> lock(task->mutex);
            task->stop = true;
            task->wake.notify_all();
        }
        for (auto& task : fake_tasks) task->thread.join();
    }
    struct DeliveryLog {
        std::mutex mutex;
        std::condition_variable changed;
        std::vector<std::pair<WifiEvent, std::string>> events;
        void Add(WifiEvent event, const std::string& data) {
            std::lock_guard<std::mutex> lock(mutex);
            events.emplace_back(event, data);
            changed.notify_all();
        }
        bool Wait(size_t count) {
            std::unique_lock<std::mutex> lock(mutex);
            return changed.wait_for(lock, 2s, [&]() { return events.size() >= count; });
        }
    };
'''

CHECKS = r'''
    int main(int argc, char** argv) {
        assert(argc == 2);
        const std::string scenario = argv[1];
        WifiManager manager;
        DeliveryLog log;
        if (scenario == "async-manager-lock") {
            std::thread::id producer_id;
            std::atomic<bool> producer_returned{false}, worker_thread{false};
            manager.event_callback_ = [&](WifiEvent event, const std::string& data) {
                // A callback must also be allowed to read the manager.
                std::lock_guard<std::mutex> lock(manager.mutex_);
                worker_thread = std::this_thread::get_id() != producer_id;
                log.Add(event, data);
            };
            std::unique_lock<std::mutex> control(manager.mutex_);
            std::thread producer([&]() {
                producer_id = std::this_thread::get_id();
                manager.NotifyEvent(WifiEvent::Connected, "network");
                producer_returned = true;
            });
            const auto deadline = std::chrono::steady_clock::now() + 200ms;
            while (!producer_returned && std::chrono::steady_clock::now() < deadline)
                std::this_thread::yield();
            const bool returned_while_locked = producer_returned;
            control.unlock();
            producer.join();
            assert(returned_while_locked && "NotifyEvent waited for manager lock on producer");
            assert(log.Wait(1) && "deferred event never delivered");
            assert(worker_thread && "callback must run on its dedicated worker");
        } else if (scenario == "callback-reentry") {
            manager.event_callback_ = [&](WifiEvent event, const std::string& data) {
                {
                    std::lock_guard<std::mutex> lock(manager.mutex_);
                    log.Add(event, data);
                }
                if (event == WifiEvent::Connected)
                    manager.NotifyEvent(WifiEvent::Disconnected, "7");
            };
            manager.NotifyEvent(WifiEvent::Connected, "network");
            assert(log.Wait(2) && "delivery held a manager/mailbox lock across callback");
            assert(log.events[1].first == WifiEvent::Disconnected);
        } else if (scenario == "worker-start-failure") {
            fail_creations = 1;
            manager.event_callback_ = [&](WifiEvent event, const std::string& data) {
                log.Add(event, data);
            };
            manager.NotifyEvent(WifiEvent::Connected, "network");
            assert(log.events.empty() && "failed startup must not call synchronously");
            manager.NotifyEvent(WifiEvent::Disconnected, "15");
            assert(log.Wait(2) && "pending final states were lost after failed startup");
            assert(log.events[0] == std::make_pair(WifiEvent::Connected, std::string("network")));
            assert(log.events[1] == std::make_pair(WifiEvent::Disconnected, std::string("15")));
        } else if (scenario == "concurrent-start") {
            delay_creation = true;
            std::array<std::atomic<int>, 6> latest{};
            manager.event_callback_ = [&](WifiEvent event, const std::string& data) {
                latest[static_cast<size_t>(event)] = std::stoi(data);
            };
            std::vector<std::thread> producers;
            for (int kind = 0; kind < 6; ++kind) {
                producers.emplace_back([&, kind]() {
                    for (int value = 1; value <= 1000; ++value)
                        manager.NotifyEvent(static_cast<WifiEvent>(kind), std::to_string(value));
                });
            }
            for (auto& producer : producers) producer.join();
            const auto deadline = std::chrono::steady_clock::now() + 2s;
            bool complete = false;
            while (!complete && std::chrono::steady_clock::now() < deadline) {
                complete = true;
                for (const auto& value : latest) complete &= value == 1000;
                if (!complete) std::this_thread::yield();
            }
            assert(complete && "concurrent startup stranded a final state");
            assert(fake_tasks.size() == 1 && "concurrent producers created multiple consumers");
        }
        #ifdef AIR_WIFI_PATCHED
        else if (scenario == "mailbox-order") {
            air::WifiEventMailbox mailbox;
            assert(mailbox.Publish(WifiEvent::Connected, "old"));
            assert(mailbox.Publish(WifiEvent::Disconnected, "15"));
            assert(mailbox.Publish(WifiEvent::Connected, "latest"));
            assert(mailbox.Publish(WifiEvent::ConfigModeExit, ""));
            air::PendingWifiEvent next;
            assert(mailbox.Take(next));
            assert(next.event == WifiEvent::Disconnected && next.Payload() == "15");
            assert(mailbox.Take(next));
            assert(next.event == WifiEvent::Connected && next.Payload() == "latest");
            assert(mailbox.Take(next) && next.event == WifiEvent::ConfigModeExit);
            assert(!mailbox.Take(next));
            assert(!mailbox.Publish(static_cast<WifiEvent>(6), "invalid"));
            assert(mailbox.Publish(WifiEvent::Connecting, "12345678901234567890123456789012MORE"));
            assert(mailbox.Take(next) && next.Payload() == "12345678901234567890123456789012");
        } else if (scenario == "mailbox-concurrent") {
            air::WifiEventMailbox mailbox;
            std::atomic<bool> done{false};
            std::vector<std::thread> producers;
            std::array<int, 6> final_values{};
            std::thread consumer([&]() {
                uint64_t last_sequence = 0;
                air::PendingWifiEvent next;
                while (true) {
                    const bool finished = done.load();
                    if (mailbox.Take(next)) {
                        assert(next.sequence > last_sequence && "pending order regressed");
                        last_sequence = next.sequence;
                        final_values[static_cast<size_t>(next.event)] = std::stoi(next.Payload());
                    } else if (finished) break;
                    else std::this_thread::yield();
                }
            });
            for (int kind = 0; kind < 6; ++kind) {
                producers.emplace_back([&, kind]() {
                    for (int i = 1; i <= 10000; ++i)
                        assert(mailbox.Publish(static_cast<WifiEvent>(kind), std::to_string(i)));
                });
            }
            for (auto& producer : producers) producer.join();
            done = true;
            consumer.join();
            for (int value : final_values)
                assert(value == 10000 && "a saturated mailbox lost a final event");
        }
        #endif
        else assert(false && "unknown scenario");
        StopFakeTasks();
    }
'''


class AirWifiEventTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shlex.split(os.environ.get("CXX", "c++"))
        if not compiler or not shutil.which(compiler[0]):
            raise unittest.SkipTest("requires a host C++ compiler")
        cls.directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.directory.cleanup)
        path = Path(cls.directory.name)
        baseline = os.environ.get("AIR_WIFI_BASELINE") == "1"
        source = VENDOR
        if not baseline:
            source = path / "wifi_manager.cc"
            generated = subprocess.run(
                ["python3", str(GENERATOR), "--source", str(VENDOR), "--output", str(source)],
                capture_output=True, text=True,
            )
            if generated.returncode:
                raise AssertionError(generated.stdout + generated.stderr)
        (path / "freertos").mkdir()
        (path / "freertos/FreeRTOS.h").write_text(
            "#pragma once\n#define pdPASS 1\n#define pdTRUE 1\n#define portMAX_DELAY 0xffffffffu\n",
            encoding="utf-8",
        )
        (path / "freertos/task.h").write_text(textwrap.dedent('''
            #pragma once
            #include "FreeRTOS.h"
            struct FakeTask;
            using TaskHandle_t = FakeTask*;
            int xTaskCreate(void (*)(void*), const char*, unsigned, void*, unsigned, TaskHandle_t*);
            void xTaskNotifyGive(TaskHandle_t);
            unsigned ulTaskNotifyTake(int, unsigned);
        '''), encoding="utf-8")
        (path / "esp_log.h").write_text(
            '#pragma once\n#include <cstdio>\n#define ESP_LOGE(tag, ...) std::fprintf(stderr, __VA_ARGS__)\n',
            encoding="utf-8",
        )
        (path / "wifi_manager.h").write_text(textwrap.dedent('''
            #pragma once
            #include <functional>
            #include <mutex>
            #include <string>
            enum class WifiEvent { Scanning, Connecting, Connected, Disconnected,
                                   ConfigModeEnter, ConfigModeExit };
            class WifiManager {
            public:
                std::mutex mutex_;
                std::function<void(WifiEvent, const std::string&)> event_callback_;
                void NotifyEvent(WifiEvent, const std::string& = "");
            };
        '''), encoding="utf-8")
        method = definition(source.read_text(encoding="utf-8"), "void WifiManager::NotifyEvent(")
        prefix = '#include "air_wifi_events.h"\n' if not baseline else ""
        driver = path / "test_wifi_events.cc"
        driver.write_text(prefix + textwrap.dedent(PLATFORM) + method + textwrap.dedent(CHECKS),
                          encoding="utf-8")
        cls.executable = path / "test_wifi_events"
        command = compiler + ["-std=c++23", "-pthread", "-Wall", "-Wextra", "-Werror",
                              "-I", str(path), "-I", str(AIR), str(driver)]
        if not baseline:
            command += [str(AIR / "air_wifi_events.cc"), "-DAIR_WIFI_PATCHED"]
        compiled = subprocess.run(command + ["-o", str(cls.executable)], capture_output=True, text=True)
        if compiled.returncode:
            raise AssertionError(compiled.stdout + compiled.stderr)

    def scenario(self, name):
        result = subprocess.run([str(self.executable), name], capture_output=True, text=True, timeout=8)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_notify_returns_while_manager_is_locked(self):
        self.scenario("async-manager-lock")

    def test_callback_can_read_manager_and_publish_again(self):
        self.scenario("callback-reentry")

    def test_worker_failure_retains_final_states_for_retry(self):
        self.scenario("worker-start-failure")

    def test_concurrent_start_has_one_worker_and_delivers_final_states(self):
        self.scenario("concurrent-start")

    def test_mailbox_coalesces_same_kind_in_last_publication_order(self):
        self.scenario("mailbox-order")

    def test_saturated_concurrent_mailbox_preserves_every_final_kind(self):
        self.scenario("mailbox-concurrent")


class AirWifiGeneratorTests(unittest.TestCase):
    def test_rejects_unknown_vendor_without_writing_output(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            source, output = path / "vendor.cc", path / "result.cc"
            source.write_text("unknown vendor version\n", encoding="utf-8")
            result = subprocess.run(
                ["python3", str(GENERATOR), "--source", str(source), "--output", str(output)],
                capture_output=True, text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("SHA256 mismatch", result.stderr)
            self.assertFalse(output.exists())

    def test_repeat_generation_is_stable_and_preserves_vendor(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "wifi_manager.cc"
            original = VENDOR.read_bytes()
            command = ["python3", str(GENERATOR), "--source", str(VENDOR), "--output", str(output)]
            subprocess.run(command, check=True, capture_output=True)
            first, mtime = output.read_bytes(), output.stat().st_mtime_ns
            subprocess.run(command, check=True, capture_output=True)
            self.assertEqual(output.read_bytes(), first)
            self.assertEqual(output.stat().st_mtime_ns, mtime)
            self.assertEqual(VENDOR.read_bytes(), original)
            self.assertEqual(first.count(b"void WifiManager::NotifyEvent("), 1)
            self.assertEqual(first.count(b'#include "air_wifi_events.h"'), 1)
            restored = first.decode("utf-8").replace(
                definition(first.decode("utf-8"), "void WifiManager::NotifyEvent("),
                definition(original.decode("utf-8"), "void WifiManager::NotifyEvent("),
            ).replace('#include "air_wifi_events.h"\n', "")
            self.assertEqual(restored.encode("utf-8"), original)

    def test_refuses_in_place_generation(self):
        original = VENDOR.read_bytes()
        result = subprocess.run(
            ["python3", str(GENERATOR), "--source", str(VENDOR), "--output", str(VENDOR)],
            capture_output=True, text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(VENDOR.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
