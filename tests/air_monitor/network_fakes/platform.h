#pragma once

#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <functional>
#include <string>
#include <utility>
#include <vector>

#include "nvs_flash.h"

enum class NetworkEvent {
    Scanning,
    Connecting,
    Connected,
    Disconnected,
    WifiConfigModeEnter,
    WifiConfigModeExit,
    ModemDetecting,
    ModemErrorNoSim,
    ModemErrorPinError,
    ModemErrorRegDenied,
    ModemErrorInitFailed,
    ModemErrorTimeout
};
enum class PowerSaveLevel { LOW_POWER, BALANCED, PERFORMANCE };
enum class WifiPowerSaveLevel { LOW_POWER, BALANCED, PERFORMANCE };
enum class WifiEvent {
    Scanning,
    Connecting,
    Connected,
    Disconnected,
    ConfigModeEnter,
    ConfigModeExit
};
enum DeviceState {
    kDeviceStateStarting,
    kDeviceStateSpeaking,
    kDeviceStateNotifying,
    kDeviceStateListening,
    kDeviceStateIdle,
    kDeviceStateWifiConfiguring
};
using NetworkEventCallback = std::function<void(NetworkEvent, const std::string&)>;
struct SavedSsid {
    std::string ssid, password;
    uint8_t channel = 0;
};

namespace network_fake {
struct State {
    int nvs_error = ESP_OK, nvs_initializes = 0, nvs_erases = 0;
    int wifi_initializes = 0, ssid_reads = 0, station_starts = 0, station_stops = 0, ap_starts = 0;
    int delay_ms = 0, timer_starts = 0;
    bool station_active = false, station_connected = false, ap_active = false;
    bool queue_application = false, application_running = false;
    DeviceState application_state = kDeviceStateStarting;
    std::vector<SavedSsid> ssids;
    std::function<void(WifiEvent, const std::string&)> callback;
    std::vector<std::function<void()>> application_queue;
    std::function<void()> after_config_read;
};
inline State state;
inline void Reset() { state = {}; }
}  // namespace network_fake

struct cJSON {};
inline cJSON* cJSON_CreateObject() {
    static cJSON object;
    return &object;
}
inline void cJSON_AddNumberToObject(cJSON*, const char*, double) {}
inline void cJSON_AddStringToObject(cJSON*, const char*, const char*) {}
inline void cJSON_AddBoolToObject(cJSON*, const char*, bool) {}
inline void cJSON_AddItemToObject(cJSON*, const char*, cJSON*) {}
inline char* cJSON_PrintUnformatted(cJSON*) {
    static char result[] = "{}";
    return result;
}
inline void cJSON_free(void*) {}
inline void cJSON_Delete(cJSON*) {}

class NetworkInterface {};
class EspNetwork : public NetworkInterface {};
class AudioCodec {
public:
    int output_volume() const { return 50; }
};
class Backlight {
public:
    int brightness() const { return 80; }
};
class Theme {
public:
    std::string name() const { return "test"; }
};
class Display {
public:
    void ShowNotification(const char*) {}
    int height() const { return 448; }
    Theme* GetTheme() { return nullptr; }
};
class Board {
public:
    virtual ~Board() = default;
    static Board& GetInstance() { return *instance_; }
    virtual std::string GetBoardType() = 0;
    virtual NetworkInterface* GetNetwork() = 0;
    virtual void StartNetwork() = 0;
    virtual bool IsNetworkConnected() const { return true; }
    virtual AudioCodec* GetAudioCodec() = 0;
    virtual void SetNetworkEventCallback(NetworkEventCallback) {}
    virtual const char* GetNetworkStateIcon() = 0;
    virtual void SetPowerSaveLevel(PowerSaveLevel) = 0;
    virtual std::string GetDeviceStatusJson() = 0;
    virtual std::string GetBoardJson() = 0;
    virtual Display* GetDisplay() {
        static Display display;
        return &display;
    }
    virtual Backlight* GetBacklight() { return nullptr; }
    virtual bool GetBatteryLevel(int&, bool&, bool&) { return false; }
    virtual bool GetTemperature(float&) { return false; }

protected:
    Board() { instance_ = this; }

private:
    inline static Board* instance_ = nullptr;
};
class Application {
public:
    static Application& GetInstance() {
        static Application application;
        return application;
    }
    void SetDeviceState(DeviceState state) { network_fake::state.application_state = state; }
    DeviceState GetDeviceState() const { return network_fake::state.application_state; }
    void ResetProtocol() {}
    void Schedule(std::function<void()> callback) {
        if (network_fake::state.queue_application)
            network_fake::state.application_queue.push_back(std::move(callback));
        else
            callback();
    }
    void Drain() {
        if (network_fake::state.application_running)
            return;
        network_fake::state.application_running = true;
        while (!network_fake::state.application_queue.empty()) {
            auto callback = std::move(network_fake::state.application_queue.front());
            network_fake::state.application_queue.erase(
                network_fake::state.application_queue.begin());
            callback();
        }
        network_fake::state.application_running = false;
    }
    void Alert(const char*, const char*, const char*, const char*) {}
};
class SystemInfo {
public:
    static std::string GetMacAddress() { return "00:01:02:03:04:05"; }
};

struct WifiManagerConfig {
    std::string ssid_prefix, language, station_hostname;
    bool show_ota_config = false, show_sleep_config = false;
};
class WifiManager {
public:
    static WifiManager& GetInstance() {
        static WifiManager manager;
        return manager;
    }
    bool Initialize(const WifiManagerConfig&) {
        ++network_fake::state.wifi_initializes;
        // The real external manager can erase NVS on these initialization failures.
        const auto error = nvs_flash_init();
        if (error == ESP_ERR_NVS_NO_FREE_PAGES || error == ESP_ERR_NVS_NEW_VERSION_FOUND) {
            nvs_flash_erase();
        }
        return error == ESP_OK;
    }
    void SetEventCallback(std::function<void(WifiEvent, const std::string&)> callback) {
        network_fake::state.callback = std::move(callback);
    }
    void StartStation() {
        // The real manager automatically stops a current AP before starting station.
        network_fake::state.ap_active = false;
        ++network_fake::state.station_starts;
        network_fake::state.station_active = true;
    }
    void StopStation() {
        ++network_fake::state.station_stops;
        network_fake::state.station_active = false;
    }
    void StartConfigAp() {
        ++network_fake::state.ap_starts;
        network_fake::state.ap_active = true;
        network_fake::state.station_active = false;
        if (network_fake::state.callback)
            network_fake::state.callback(WifiEvent::ConfigModeEnter, "");
    }
    bool IsConfigMode() const {
        const bool active = network_fake::state.ap_active;
        if (auto hook = std::move(network_fake::state.after_config_read)) {
            network_fake::state.after_config_read = {};
            hook();
        }
        return active;
    }
    bool IsConnected() const {
        return network_fake::state.station_active && network_fake::state.station_connected;
    }
    int GetRssi() const { return -60; }
    std::string GetSsid() const { return "test-ap"; }
    int GetChannel() const { return 1; }
    std::string GetIpAddress() const { return "127.0.0.1"; }
    std::string GetApSsid() const { return "config-ap"; }
    std::string GetApWebUrl() const { return "http://192.168.4.1"; }
    void SetPowerSaveLevel(WifiPowerSaveLevel) {}
};
class SsidManager {
public:
    static SsidManager& GetInstance() {
        static SsidManager manager;
        return manager;
    }
    const std::vector<SavedSsid>& GetSsidList() const {
        ++network_fake::state.ssid_reads;
        return network_fake::state.ssids;
    }
};

struct esp_timer_create_args_t {
    void (*callback)(void*) = nullptr;
    void* arg = nullptr;
    int dispatch_method = 0;
    const char* name = nullptr;
    bool skip_unhandled_events = false;
};
struct FakeTimer {
    esp_timer_create_args_t args;
    bool active = false;
};
using esp_timer_handle_t = FakeTimer*;
constexpr int ESP_TIMER_TASK = 0;
inline int esp_timer_create(const esp_timer_create_args_t* args, esp_timer_handle_t* timer) {
    *timer = new FakeTimer{*args, false};
    return ESP_OK;
}
inline int esp_timer_start_once(esp_timer_handle_t timer, uint64_t) {
    ++network_fake::state.timer_starts;
    timer->active = true;
    return ESP_OK;
}
inline int esp_timer_stop(esp_timer_handle_t timer) {
    timer->active = false;
    return ESP_OK;
}
inline int esp_timer_delete(esp_timer_handle_t timer) {
    delete timer;
    return ESP_OK;
}
inline void FireTimer(esp_timer_handle_t timer) {
    if (!timer->active)
        std::abort();
    timer->active = false;
    timer->args.callback(timer->args.arg);
}
constexpr int ESP_MAC_WIFI_STA = 0;
inline int esp_read_mac(uint8_t* mac, int) {
    for (int index = 0; index < 6; ++index)
        mac[index] = static_cast<uint8_t>(index);
    return ESP_OK;
}
inline void vTaskDelay(int ticks) { network_fake::state.delay_ms += ticks; }
inline void vTaskDelete(void*) {}
inline int xTaskCreate(void (*callback)(void*), const char*, int, void* arg, int, void*) {
    callback(arg);
    return 1;
}
#define pdMS_TO_TICKS(ms) (ms)
#define ESP_LOGI(...) ((void)0)
#define ESP_LOGW(...) ((void)0)
#define ESP_LOGE(...) ((void)0)

#define BOARD_TYPE "host-test"
#define BOARD_NAME "host-test"
#define BOARD_MANUFACTURER "host-test"
#define MATERIAL_SYMBOLS_WIFI "wifi"
#define MATERIAL_SYMBOLS_WIFI_OFF "offline"
#define MATERIAL_SYMBOLS_WIFI_1_BAR "wifi1"
#define MATERIAL_SYMBOLS_WIFI_2_BAR "wifi2"
namespace Lang {
inline constexpr char CODE[] = "en-US";
namespace Strings {
inline constexpr char CONNECT_TO_HOTSPOT[] = "Connect to ";
inline constexpr char ACCESS_VIA_BROWSER[] = " at ";
inline constexpr char WIFI_CONFIG_MODE[] = "WiFi config";
inline constexpr char ENTERING_WIFI_CONFIG_MODE[] = "Entering config";
}  // namespace Strings
namespace Sounds {
inline constexpr char OGG_WIFICONFIG[] = "config";
}
}  // namespace Lang
