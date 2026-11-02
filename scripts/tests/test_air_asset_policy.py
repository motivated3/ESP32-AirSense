"""Execute the production asset boot path and MCP setter with board policy."""

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


class AirAssetPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shlex.split(os.environ.get("CXX", "c++"))
        if not compiler or shutil.which(compiler[0]) is None:
            raise unittest.SkipTest("requires a host C++23 compiler")
        app = (ROOT / "main/application.cc").read_text()
        mcp = (ROOT / "main/mcp_server.cc").read_text()
        registration_start = mcp.index('AddUserOnlyTool("self.assets.set_download_url"')
        callback = definition(mcp[registration_start:], "[](const PropertyList&")
        registration_end = mcp.index(callback, registration_start) + len(callback)
        registration = mcp[registration_start:registration_end] + ");"
        platform = r'''
            #include <cassert>
            #include <cstdio>
            #include <cstdint>
            #include <functional>
            #include <initializer_list>
            #include <map>
            #include <string>
            #include <utility>
            #define TAG "HostAssetPolicy"
            #define BOARD_NAME "host-air"
            #define ESP_LOGW(...) ((void)0)
            #define ESP_LOGI(...) ((void)0)
            #define pdMS_TO_TICKS(value) (value)
            int delays = 0, erases = 0, writes = 0, flash_writes = 0, reboots = 0;
            std::map<std::string, std::string> nvs{{"download_url", "https://old.invalid/assets.bin"}};
            void vTaskDelay(int value) { delays += value; }
            struct Settings {
                Settings(const char* space, bool = false) { assert(std::string(space) == "assets"); }
                std::string GetString(const char* key) { return nvs[key]; }
                void EraseKey(const char* key) { ++erases; nvs.erase(key); }
                void SetString(const char* key, const std::string& value) { ++writes; nvs[key] = value; }
            };
            struct Display {
                void SetChatMessage(const char*, const char*) {}
                void SetEmotion(const char*) {}
            };
            enum class PowerSaveLevel { PERFORMANCE, LOW_POWER };
            enum DeviceState { kDeviceStateIdle, kDeviceStateUpgrading, kDeviceStateActivating };
            struct Board {
                bool allow_install = true;
                int power_changes = 0;
                Display display;
                static Board& GetInstance() { static Board board; return board; }
                bool AllowFirmwareInstall() const { return allow_install; }
                Display* GetDisplay() { return &display; }
                void SetPowerSaveLevel(PowerSaveLevel) { ++power_changes; }
            };
            struct Assets {
                int downloads = 0, applications = 0;
                std::string downloaded;
                static Assets& GetInstance() { static Assets assets; return assets; }
                bool partition_valid() const { return true; }
                bool Download(std::string url, std::function<void(int, size_t)> progress) {
                    ++downloads; ++flash_writes; downloaded = std::move(url);
                    progress(100, 1024);
                    return true;
                }
                bool Apply() { ++applications; return true; }
            };
            namespace Lang::Strings {
                constexpr const char *FOUND_NEW_ASSETS = "%s", *LOADING_ASSETS = "loading",
                    *PLEASE_WAIT = "wait", *ERROR = "error", *DOWNLOAD_ASSETS_FAILED = "failed";
            }
            namespace Lang::Sounds {
                constexpr const char *OGG_UPGRADE = "upgrade", *OGG_EXCLAMATION = "error";
            }
            struct Application {
                bool assets_version_checked_ = false;
                int alerts = 0, state_changes = 0;
                void CheckAssetsVersion();
                void Alert(const char*, const char*, const char*, const char*) { ++alerts; }
                void SetDeviceState(DeviceState) { ++state_changes; }
                void Schedule(std::function<void()> callback) { callback(); }
                void Reboot() { ++reboots; }
            };
            using ReturnValue = bool;
            enum PropertyType { kPropertyTypeString };
            struct Property {
                Property(const char*, PropertyType) {}
                template<class T> T value() const { return T("https://new.invalid/assets.bin"); }
            };
            struct PropertyList {
                PropertyList(std::initializer_list<Property>) {}
                Property operator[](const char* key) const {
                    assert(std::string(key) == "url");
                    return Property(key, kPropertyTypeString);
                }
            };
            struct McpServer {
                std::function<ReturnValue(const PropertyList&)> callback;
                void RegisterAssetSetter();
                void AddUserOnlyTool(const char* name, const char*, const PropertyList&,
                                     decltype(callback) handler) {
                    assert(std::string(name) == "self.assets.set_download_url");
                    callback = std::move(handler);
                }
            };
        '''
        checks = r'''
            int main(int argc, char** argv) {
                assert(argc == 2);
                const std::string scenario = argv[1];
                auto& board = Board::GetInstance();
                auto& assets = Assets::GetInstance();
                board.allow_install = scenario.ends_with("allowed");
                if (scenario.starts_with("boot")) {
                    Application app;
                    app.CheckAssetsVersion();
                    app.CheckAssetsVersion();
                    assert(assets.applications == 1 && "existing local assets must still apply once");
                    if (board.allow_install) {
                        assert(assets.downloads == 1 && flash_writes == 1 && erases == 1);
                        assert(assets.downloaded == "https://old.invalid/assets.bin" && nvs.empty());
                        assert(delays == 4000 && board.power_changes == 2 && app.state_changes == 1);
                    } else {
                        assert(erases == 0 && "AIR must preserve a pending legacy assets URL");
                        assert(nvs.at("download_url") == "https://old.invalid/assets.bin");
                        assert(assets.downloads == 0 && flash_writes == 0 && reboots == 0 &&
                               "AIR must not download, flash or reboot for online assets");
                        assert(delays == 0 && app.alerts == 0 && app.state_changes == 0 &&
                               board.power_changes == 0);
                    }
                } else {
                    McpServer server;
                    server.RegisterAssetSetter();
                    assert(server.callback && "the actual user-only tool registration must execute");
                    const bool result = server.callback(PropertyList{});
                    if (board.allow_install) {
                        assert(result && writes == 1 && nvs.at("download_url") == "https://new.invalid/assets.bin");
                    } else {
                        assert(!result && "AIR must reject the MCP asset URL setter");
                        assert(writes == 0 && erases == 0 && flash_writes == 0 && reboots == 0 &&
                               nvs.at("download_url") == "https://old.invalid/assets.bin");
                    }
                }
            }
        '''
        cls.directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.directory.cleanup)
        path = Path(cls.directory.name)
        driver = path / "air_asset_policy.cc"
        cls.executable = path / "air_asset_policy"
        driver.write_text(textwrap.dedent(platform) + definition(app, "void Application::CheckAssetsVersion()") +
                          "\nvoid McpServer::RegisterAssetSetter() {\n" + registration + "\n}\n" +
                          textwrap.dedent(checks))
        compiled = subprocess.run(compiler + ["-std=c++23", str(driver), "-o", str(cls.executable)],
                                  capture_output=True, text=True)
        if compiled.returncode:
            raise AssertionError(compiled.stdout + compiled.stderr)

    def run_scenario(self, scenario):
        result = subprocess.run([str(self.executable), scenario], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_air_applies_existing_assets_and_preserves_pending_url_without_flash(self):
        self.run_scenario("boot-denied")

    def test_other_boards_keep_legacy_asset_download(self):
        self.run_scenario("boot-allowed")

    def test_air_rejects_mcp_asset_url_write(self):
        self.run_scenario("setter-denied")

    def test_other_boards_keep_mcp_asset_url_write(self):
        self.run_scenario("setter-allowed")
