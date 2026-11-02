"""Execute the production automatic theme adapter with real solar and UI state."""
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest

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


class AirAutoThemeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.directory.cleanup)
        path = Path(cls.directory.name)
        source = (AIR / "air_display.cc").read_text()
        methods = "\n".join(definition(source, name) for name in (
            "void AirDisplay::UpdateAutoTheme(", "void AirDisplay::SynchronizeSolar(",
            "void AirDisplay::SetTheme("))
        driver = path / "auto_theme.cc"
        driver.write_text(r'''
            #include <cassert>
            #include <cstdint>
            #include <functional>
            #include <memory>
            #include <string>
            #include "air_solar_theme.h"
            #include "air_ui_state.h"
            bool lock_available = true;
            struct DisplayLockGuard {
                template<class T> explicit DisplayLockGuard(T*) {}
                explicit operator bool() const { return lock_available; }
            };
            namespace air {
            struct Theme { std::string value; const std::string& name() { return value; } };
            struct LvglThemeManager {
                static LvglThemeManager& GetInstance() { static LvglThemeManager manager; return manager; }
                Theme* GetTheme(const std::string& name) {
                    static Theme light{"light"}, dark{"dark"};
                    return name=="dark" ? &dark : &light;
                }
            };
            struct View { int themes=0; void ApplyTheme() { ++themes; } };
            struct AirDisplay {
                AirUiState state_;
                SolarThemeClock solar_clock_;
                uint64_t next_solar_refresh_=0;
                uint32_t preferences_generation_=0;
                int physical=0, backlight=0;
                Theme* current_theme_=nullptr;
                std::unique_ptr<View> view_=std::make_unique<View>();
                struct Callbacks { std::function<void(int)> brightness; } callbacks_;
                AirDisplay() { callbacks_.brightness=[this](int value) {
                    backlight=value; RequestBrightness(value);
                }; }
                void RequestBrightness(int value) { physical=value; }
                void UpdateAutoTheme(uint64_t now_ms);
                void SynchronizeSolar(std::optional<SolarLocation>, int64_t, uint64_t);
                void SetTheme(Theme*);
            };
        ''' + methods + r'''
            }
            int main(int argc, char** argv) {
                assert(argc==2); const std::string scenario=argv[1];
                air::AirDisplay display;
                display.state_.SetThemeMode(air::ThemeMode::Night);
                display.state_.SetBrightness(12);
                display.state_.SetThemeMode(air::ThemeMode::Auto);
                display.state_.SetPage(air::Page::Trend);
                display.state_.SetDisplayOn(false);
                if (scenario=="unavailable") {
                    display.UpdateAutoTheme(1000);
                    assert(display.state_.night() && display.physical==0);
                    display.solar_clock_.SetLocation({39904000,116407000});
                    display.UpdateAutoTheme(61000);
                    assert(display.state_.night() && display.preferences_generation_==0);
                } else if (scenario=="offline-sunrise") {
                    display.solar_clock_.SetLocation({39904000,116407000});
                    assert(display.solar_clock_.Synchronize(1782073800000LL,1000)); // 2026-06-21 20:30Z
                    display.UpdateAutoTheme(1000);
                    assert(display.state_.night() && display.physical==0);
                    display.UpdateAutoTheme(1801000);
                    assert(!display.state_.night() && display.physical==70);
                    assert(display.backlight==70 && "auto must update the board brightness adapter");
                    assert(display.view_->themes==1 && display.preferences_generation_==1);
                    for(uint64_t t=1861000;t<7201000;t+=60000) display.UpdateAutoTheme(t);
                    assert(display.preferences_generation_==1 && "unchanged themes must not dirty NVS");
                    assert(display.state_.theme_mode()==air::ThemeMode::Auto);
                    assert(display.state_.page()==air::Page::Trend && !display.state_.display_on());
                } else if (scenario=="offscreen-asset-refresh") {
                    auto& themes=air::LvglThemeManager::GetInstance();
                    display.current_theme_=themes.GetTheme("dark");
                    display.solar_clock_.SetLocation({39904000,116407000});
                    assert(display.solar_clock_.Synchronize(1782075600000LL,1000));
                    display.UpdateAutoTheme(1000);
                    assert(!display.state_.night() && !display.state_.display_on());
                    display.SetTheme(display.current_theme_);
                    assert(display.state_.theme_mode()==air::ThemeMode::Auto && !display.state_.night());
                } else if (scenario=="manual") {
                    display.solar_clock_.SetLocation({39904000,116407000});
                    assert(display.solar_clock_.Synchronize(1782075600000LL,1000));
                    display.state_.SetThemeMode(air::ThemeMode::Night);
                    display.UpdateAutoTheme(1000);
                    assert(display.state_.night() && display.view_->themes==0);
                } else if (scenario=="sync") {
                    display.SynchronizeSolar(air::SolarLocation{39904000,116407000},1782075600000LL,1000);
                    assert(display.preferences_generation_==1);
                    display.SynchronizeSolar(air::SolarLocation{39904000,116407000},1782075660000LL,61000);
                    assert(display.preferences_generation_==1);
                    display.SynchronizeSolar(std::nullopt,1782075720000LL,121000);
                    assert(display.solar_clock_.location().latitude_e6==39904000);
                    display.UpdateAutoTheme(121000);
                    assert(!display.state_.night());
                } else if (scenario=="failed-sync") {
                    lock_available=false;
                    display.SynchronizeSolar(air::SolarLocation{39904000,116407000},1782075600000LL,1000);
                    assert(!display.solar_clock_.location().valid() && display.preferences_generation_==0);
                    lock_available=true;
                    display.SynchronizeSolar(air::SolarLocation{39904000,116407000},0,1000);
                    assert(!display.solar_clock_.location().valid() && display.preferences_generation_==0);
                } else {
                    assert(scenario=="external-theme");
                    air::Theme dark{"dark"}, light{"light"};
                    display.SetTheme(&dark); // Asset refresh preserves automatic mode.
                    assert(display.state_.theme_mode()==air::ThemeMode::Auto);
                    display.SetTheme(&light); // An explicit change takes manual control.
                    assert(!display.state_.night() && display.state_.theme_mode()==air::ThemeMode::Day);
                }
            }
        ''')
        cls.executable = path / "auto_theme"
        compiler = shlex.split(os.environ.get("CXX", "c++"))
        subprocess.run(compiler + ["-std=c++23", "-Wall", "-Wextra", "-Werror", f"-I{AIR}",
                                  f"-I{ROOT / 'main'}", str(driver), str(AIR / "air_solar_theme.cc"),
                                  str(AIR / "air_ui_state.cc"), "-o", str(cls.executable)],
                       check=True, capture_output=True, text=True)

    def run_scenario(self, scenario):
        result = subprocess.run([str(self.executable), scenario], capture_output=True, text=True,
                                cwd=self.directory.name)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


for scenario in ("unavailable", "offline-sunrise", "offscreen-asset-refresh", "manual", "sync", "failed-sync", "external-theme"):
    setattr(AirAutoThemeTests, "test_" + scenario.replace("-", "_"),
            lambda self, value=scenario: self.run_scenario(value))
