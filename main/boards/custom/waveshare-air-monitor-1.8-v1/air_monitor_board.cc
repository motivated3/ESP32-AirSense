#include <driver/spi_master.h>
#include <esp_lcd_panel_vendor.h>
#include <esp_lcd_sh8601.h>
#include <esp_lcd_touch_ft5x06.h>
#include <esp_lvgl_port.h>
#include <cJSON.h>
#include <wifi_manager.h>
#include <algorithm>
#include <cstdio>
#include "air_alert_sound.h"
#include "air_audio_codec.h"
#include "air_display.h"
#include "air_ha_upload.h"
#include "air_wifi_board.h"
#include "application.h"
#include "codecs/es8311_audio_codec.h"
#include "config.h"
#include "mcp_server.h"
#include "storage_init.h"
#include "wifi_board.h"

namespace {
constexpr const char* kTag = "AirBoardV1";
const sh8601_lcd_init_cmd_t kPanelInit[] = {
    {0x11, (uint8_t[]){0x00}, 0, 120},
    {0x44, (uint8_t[]){0x01, 0xD1}, 2, 0},
    {0x35, (uint8_t[]){0x00}, 1, 0},
    {0x53, (uint8_t[]){0x20}, 1, 10},
    {0x2A, (uint8_t[]){0x00, 0x00, 0x01, 0x6F}, 4, 0},
    {0x2B, (uint8_t[]){0x00, 0x00, 0x01, 0xBF}, 4, 0},
    {0x51, (uint8_t[]){0x00}, 1, 10},
    {0x29, (uint8_t[]){0x00}, 0, 10},
};
class AirBacklight : public Backlight {
public:
    explicit AirBacklight(air::AirDisplay& display) : display_(display) {}
    void SetBrightness(uint8_t percent, bool permanent = false) override {
        percent = std::clamp<uint8_t>(percent, 1, 100);
        if (permanent)
            display_.RequestUserBrightness(percent);
        else
            SetBrightnessImpl(percent);
    }
    uint8_t brightness() const override { return level_.load(); }

protected:
    void SetBrightnessImpl(uint8_t percent) override {
        level_ = percent;
        display_.RequestBrightness(percent);
    }

private:
    std::atomic<uint8_t> level_{0};
    air::AirDisplay& display_;
};
class WaveshareAirMonitorV1 : public air::AirWifiBoard {
public:
    WaveshareAirMonitorV1() {
        i2c_master_bus_config_t bus{};
        bus.i2c_port = I2C_NUM_0;
        bus.sda_io_num = AUDIO_CODEC_I2C_SDA_PIN;
        bus.scl_io_num = AUDIO_CODEC_I2C_SCL_PIN;
        bus.clk_source = I2C_CLK_SRC_DEFAULT;
        bus.glitch_ignore_cnt = 7;
        bus.flags.enable_internal_pullup = true;
        ESP_ERROR_CHECK(i2c_new_master_bus(&bus, &bus_));
        ESP_ERROR_CHECK(hardware_.Initialize(bus_) ? ESP_OK : ESP_FAIL);
        InitializeDisplay();
        InitializeTouch();
        if (!upload_.Start([this](std::optional<air::SolarLocation> location, int64_t utc_ms,
                                  uint64_t uptime_ms) {
                display_->SynchronizeSolar(location, utc_ms, uptime_ms);
            }))
            ESP_LOGE(kTag, "HA upload task failed to start");
        if (!sensors_.Start(bus_, &upload_)) {
            ESP_LOGE(kTag, "Sensor task failed to start");
            upload_.FinishCollection(0);
        }
        if (!hardware_.Start(
                [this](air::ButtonAction action) {
                    if (action == air::ButtonAction::WakeHome)
                        display_->WakeHome();
                    else if (action == air::ButtonAction::ToggleDisplay)
                        display_->ToggleScreen();
                },
                [this]() {
                    sensors_.Stop();
                    upload_.Stop();
                    Application::GetInstance().Schedule([this]() {
                        Application::GetInstance().PrepareForShutdown();
                        shutdown_preferences_flushed_ = display_->FlushPreferences();
                    });
                },
                [this]() {
                    return air::ShutdownProgress{Application::GetInstance().IsShutdownReady(),
                                                 sensors_.stopped() && upload_.stopped(),
                                                 shutdown_preferences_flushed_.load()};
                }))
            ESP_LOGE(kTag, "Input task failed to start");
        InitializeTools();
    }
    AudioCodec* GetAudioCodec() override {
        static air::AirAudioCodec codec(
            [this](int volume) { display_->RequestVolume(volume); }, bus_, I2C_NUM_0,
            AUDIO_INPUT_SAMPLE_RATE, AUDIO_OUTPUT_SAMPLE_RATE, AUDIO_I2S_GPIO_MCLK,
            AUDIO_I2S_GPIO_BCLK, AUDIO_I2S_GPIO_WS, AUDIO_I2S_GPIO_DOUT, AUDIO_I2S_GPIO_DIN,
            AUDIO_CODEC_PA_PIN, AUDIO_CODEC_ES8311_ADDR);
        return &codec;
    }
    Display* GetDisplay() override { return display_; }
    Backlight* GetBacklight() override { return backlight_; }
    bool AllowFirmwareInstall() const override { return false; }
    bool IsVoiceEnabled() const override {
        return !hardware_.IsShuttingDown() && display_ && display_->VoiceEnabled();
    }
    bool AllowChatControl(DeviceState state) const override {
        return air::CanToggleVoice(state, WifiManager::GetInstance().IsConnected(),
                                   IsVoiceEnabled());
    }
    bool GetBatteryLevel(int& level, bool& charging, bool& discharging) override {
        const auto power = hardware_.Snapshot();
        if (!power.valid || !power.battery_present || power.battery_percent < 0)
            return false;
        level = power.battery_percent;
        charging = power.charging;
        discharging = power.discharging;
        return true;
    }

protected:
    bool AllowAutomaticProvisioning() const override { return false; }

private:
    void InitializeDisplay() {
        spi_bus_config_t spi{};
        spi.sclk_io_num = EXAMPLE_PIN_NUM_LCD_PCLK;
        spi.data0_io_num = EXAMPLE_PIN_NUM_LCD_DATA0;
        spi.data1_io_num = EXAMPLE_PIN_NUM_LCD_DATA1;
        spi.data2_io_num = EXAMPLE_PIN_NUM_LCD_DATA2;
        spi.data3_io_num = EXAMPLE_PIN_NUM_LCD_DATA3;
        spi.max_transfer_sz = DISPLAY_WIDTH * DISPLAY_HEIGHT * sizeof(uint16_t);
        spi.flags = SPICOMMON_BUSFLAG_QUAD;
        ESP_ERROR_CHECK(spi_bus_initialize(SPI2_HOST, &spi, SPI_DMA_CH_AUTO));
        esp_lcd_panel_io_spi_config_t io_config{};
        io_config.cs_gpio_num = EXAMPLE_PIN_NUM_LCD_CS;
        io_config.dc_gpio_num = GPIO_NUM_NC;
        io_config.pclk_hz = 40000000;
        io_config.trans_queue_depth = 10;
        io_config.lcd_cmd_bits = 32;
        io_config.lcd_param_bits = 8;
        io_config.flags.quad_mode = true;
        esp_lcd_panel_io_handle_t io;
        ESP_ERROR_CHECK(esp_lcd_new_panel_io_spi(SPI2_HOST, &io_config, &io));
        sh8601_vendor_config_t vendor{};
        vendor.init_cmds = kPanelInit;
        vendor.init_cmds_size = sizeof(kPanelInit) / sizeof(kPanelInit[0]);
        vendor.flags.use_qspi_interface = true;
        esp_lcd_panel_dev_config_t panel_config{};
        panel_config.reset_gpio_num = GPIO_NUM_NC;
        panel_config.flags.reset_active_high = true;
        panel_config.rgb_ele_order = LCD_RGB_ELEMENT_ORDER_RGB;
        panel_config.bits_per_pixel = 16;
        panel_config.vendor_config = &vendor;
        esp_lcd_panel_handle_t panel;
        ESP_ERROR_CHECK(esp_lcd_new_panel_sh8601(io, &panel_config, &panel));
        ESP_ERROR_CHECK(esp_lcd_panel_reset(panel));
        ESP_ERROR_CHECK(esp_lcd_panel_init(panel));
        ESP_ERROR_CHECK(esp_lcd_panel_invert_color(panel, false));
        ESP_ERROR_CHECK(esp_lcd_panel_mirror(panel, false, false));
        air::AirViewCallbacks callbacks;
        callbacks.voice = [this]() {
            auto& app = Application::GetInstance();
            // Check again on the application task: state can change after the touch.
            app.Schedule([this, &app]() {
                if (app.GetDeviceState() == kDeviceStateIdle &&
                    air::CanToggleVoice(app.GetDeviceState(),
                                        WifiManager::GetInstance().IsConnected(), IsVoiceEnabled()))
                    app.ToggleChatState();
            });
        };
        callbacks.stop_voice = []() { Application::GetInstance().EndVoiceSession(); };
        callbacks.brightness = [this](int percent) { backlight_->SetBrightness(percent); };
        callbacks.volume = [this](int percent) {
            if (!hardware_.IsShuttingDown())
                GetAudioCodec()->SetOutputVolume(percent);
        };
        callbacks.alert_sound = [this](uint32_t generation) {
            Application::GetInstance().Schedule([this, generation]() {
                auto& app = Application::GetInstance();
                if (!hardware_.IsShuttingDown() && display_->CanSoundAlert(generation) &&
                    app.GetDeviceState() == kDeviceStateIdle &&
                    GetAudioCodec()->output_volume() > 0)
                    air::TryPlayAirAlertTone(app.GetAudioService());
            });
        };
        callbacks.voice_enabled = [](bool enabled) {
            Application::GetInstance().Schedule(
                [enabled]() { Application::GetInstance().SetVoiceEnabled(enabled); });
        };
        callbacks.confirmed_action = [this](air::DeviceAction action) {
            if (action == air::DeviceAction::Shutdown)
                hardware_.RequestShutdown();
            else
                Application::GetInstance().Schedule([this]() { ConfigureWifi(); });
        };
        callbacks.cancel_config = []() {
            Application::GetInstance().Schedule(
                []() { WifiManager::GetInstance().StopConfigAp(); });
        };
        display_ = new air::AirDisplay(io, panel, sensors_, hardware_, std::move(callbacks));
        backlight_ = new AirBacklight(*display_);
        backlight_->SetBrightness(display_->InitialBrightness());
    }
    void InitializeTouch() {
        esp_lcd_touch_config_t config{};
        config.x_max = DISPLAY_WIDTH;
        config.y_max = DISPLAY_HEIGHT;
        config.rst_gpio_num = GPIO_NUM_NC;
        config.int_gpio_num = GPIO_NUM_21;
        esp_lcd_panel_io_i2c_config_t io_config{};
        io_config.dev_addr = ESP_LCD_TOUCH_IO_I2C_FT5x06_ADDRESS;
        io_config.control_phase_bytes = 1;
        io_config.lcd_cmd_bits = 8;
        io_config.flags.disable_control_phase = true;
        io_config.scl_speed_hz = 400000;
        esp_lcd_panel_io_handle_t io;
        ESP_ERROR_CHECK(esp_lcd_new_panel_io_i2c(bus_, &io_config, &io));
        esp_lcd_touch_handle_t touch;
        ESP_ERROR_CHECK(esp_lcd_touch_new_i2c_ft5x06(io, &config, &touch));
        lvgl_port_touch_cfg_t port{};
        port.disp = lv_display_get_default();
        port.handle = touch;
        display_->SetTouch(lvgl_port_add_touch(&port));
    }
    void ConfigureWifi() {
        if (!GetStorageInitResult().available) {
            display_->ShowNotification("存储不可用，无法配网", 4000);
            return;
        }
        if (WifiManager::GetInstance().IsConfigMode())
            return;
        auto& app = Application::GetInstance();
        const auto state = app.GetDeviceState();
        const bool voice = IsVoiceEnabled();
        if (state == kDeviceStateConnecting || state == kDeviceStateListening ||
            state == kDeviceStateSpeaking || state == kDeviceStateNotifying)
            app.SetVoiceEnabled(false);
        esp_timer_stop(connect_timer_);
        WifiManager::GetInstance().StopStation();
        StartWifiConfigMode();
        if (voice)
            app.SetVoiceEnabled(true);
    }
    void InitializeTools() {
        auto& mcp = McpServer::GetInstance();
        mcp.AddTool("self.air_quality.read",
                    "Read measured CO2 (ppm), formaldehyde (ppb), SCD41 temperature/humidity, "
                    "validity and sample age. Warming/stale data must be stated.",
                    PropertyList(), [this](const PropertyList&) -> ReturnValue {
                        const auto snapshot = sensors_.Snapshot();
                        auto* root = cJSON_CreateObject();
                        auto add = [root, &snapshot](const char* name, float value,
                                                     const air::ChannelState& state,
                                                     const char* unit) {
                            auto* item = cJSON_AddObjectToObject(root, name);
                            if (state.has_value && state.connected)
                                cJSON_AddNumberToObject(item, "value", value);
                            else
                                cJSON_AddNullToObject(item, "value");
                            cJSON_AddStringToObject(item, "unit", unit);
                            cJSON_AddBoolToObject(item, "connected", state.connected);
                            cJSON_AddBoolToObject(item, "ready", state.ready);
                            cJSON_AddBoolToObject(item, "within_spec", state.within_spec);
                            cJSON_AddBoolToObject(item, "stale", state.stale);
                            if (state.has_value)
                                cJSON_AddNumberToObject(item, "age_ms",
                                                        snapshot.now_ms - state.last_value_ms);
                            else
                                cJSON_AddNullToObject(item, "age_ms");
                        };
                        add("co2", snapshot.scd.ppm, snapshot.co2, "ppm");
                        add("hcho", snapshot.sfa.ppb, snapshot.hcho, "ppb");
                        add("temperature", snapshot.scd.temperature, snapshot.co2, "C");
                        add("humidity", snapshot.scd.humidity, snapshot.co2, "%RH");
                        cJSON_AddStringToObject(root, "temperature_humidity_source", "SCD41");
                        char* printed = cJSON_PrintUnformatted(root);
                        std::string result = printed ? printed : "{}";
                        cJSON_free(printed);
                        cJSON_Delete(root);
                        return result;
                    });
        mcp.AddTool("self.system.reconfigure_wifi",
                    "Request Wi-Fi setup. The device screen must confirm within 30 seconds; this "
                    "tool cannot confirm or erase settings.",
                    PropertyList(), [this](const PropertyList&) {
                        display_->RequestDeviceAction(air::DeviceAction::ConfigureWifi);
                        return true;
                    });
    }
    i2c_master_bus_handle_t bus_ = nullptr;
    std::atomic<bool> shutdown_preferences_flushed_{false};
    air::AirHaUpload upload_;
    air::AirSensors sensors_;
    air::AirHardware hardware_;
    air::AirDisplay* display_ = nullptr;
    AirBacklight* backlight_ = nullptr;
};
}  // namespace

DECLARE_BOARD(WaveshareAirMonitorV1);
