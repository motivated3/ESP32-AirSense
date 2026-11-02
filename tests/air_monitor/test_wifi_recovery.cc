// Compile the real WiFi board policy with only hardware/RTOS boundaries replaced.
#include "network_fakes/board.h"
#include "storage_init.h"
#include "test_support.h"

#ifndef WIFI_BOARD_IMPLEMENTATION
#define WIFI_BOARD_IMPLEMENTATION "../../main/boards/common/wifi_board.cc"
#endif
#include WIFI_BOARD_IMPLEMENTATION
#include "../../main/boards/custom/waveshare-air-monitor-1.8-v1/air_wifi_board.h"

#include <cstring>

int nvs_flash_init() {
    ++network_fake::state.nvs_initializes;
    return network_fake::state.nvs_error;
}
int nvs_flash_erase() {
    ++network_fake::state.nvs_erases;
    return ESP_OK;
}

class LegacyBoard : public WifiBoard {
public:
    void ExpireConnectTimer() { FireTimer(connect_timer_); }
};
class OfflineBoard : public LegacyBoard {
protected:
    bool AllowAutomaticProvisioning() const override { return false; }
};
class AirOfflineBoard : public air::AirWifiBoard {
public:
    void BeginConfig() { StartWifiConfigMode(); }

protected:
    bool AllowAutomaticProvisioning() const override { return false; }
};

static void ResetStorage(int error = ESP_OK) {
    network_fake::Reset();
    network_fake::state.nvs_error = error;
    InitializeDefaultNvs(StorageInitPolicy::PreserveOnFailure);
}
static void RecordEvents(WifiBoard& board, std::vector<NetworkEvent>& events) {
    board.SetNetworkEventCallback(
        [&events](NetworkEvent event, const std::string&) { events.push_back(event); });
}

static void NoSsidStaysOfflineWithoutProvisioning() {
    ResetStorage();
    OfflineBoard board;
    std::vector<NetworkEvent> events;
    RecordEvents(board, events);
    board.StartNetwork();
    CHECK(network_fake::state.wifi_initializes == 1);
    CHECK(network_fake::state.station_starts == 0);
    CHECK(network_fake::state.ap_starts == 0);
    CHECK(network_fake::state.delay_ms == 0);
    CHECK(network_fake::state.nvs_erases == 0);
    CHECK(network_fake::state.application_state == kDeviceStateStarting);
    CHECK(events == std::vector<NetworkEvent>{NetworkEvent::Disconnected});
}

static void LegacyNoSsidStillProvisions() {
    ResetStorage();
    LegacyBoard board;
    board.StartNetwork();
    CHECK(network_fake::state.ap_starts == 1);
    CHECK(board.IsInWifiConfigMode());
    CHECK(network_fake::state.application_state == kDeviceStateWifiConfiguring);
    CHECK(network_fake::state.nvs_erases == 0);
}

static void TimeoutKeepsStationWhenProvisioningDisabled() {
    ResetStorage();
    network_fake::state.ssids.push_back({"saved-ap", "password", 1});
    OfflineBoard board;
    std::vector<NetworkEvent> events;
    RecordEvents(board, events);
    board.StartNetwork();
    CHECK(network_fake::state.station_active);
    board.ExpireConnectTimer();
    CHECK(network_fake::state.station_starts == 1);
    CHECK(network_fake::state.station_stops == 0);
    CHECK(network_fake::state.station_active);
    CHECK(network_fake::state.ap_starts == 0);
    CHECK(!board.IsInWifiConfigMode());
    CHECK(network_fake::state.nvs_erases == 0);
    CHECK(events == std::vector<NetworkEvent>{NetworkEvent::Disconnected});
}

static void LegacyTimeoutStillProvisions() {
    ResetStorage();
    network_fake::state.ssids.push_back({"saved-ap", "password", 1});
    LegacyBoard board;
    board.StartNetwork();
    CHECK(network_fake::state.station_active);
    board.ExpireConnectTimer();
    CHECK(network_fake::state.station_stops == 1);
    CHECK(!network_fake::state.station_active);
    CHECK(network_fake::state.ap_starts == 1);
    CHECK(board.IsInWifiConfigMode());
    CHECK(network_fake::state.application_state == kDeviceStateWifiConfiguring);
    CHECK(network_fake::state.nvs_erases == 0);
}

template <typename TestBoard>
static void CheckUnavailableStorageSkipsManager() {
    ResetStorage(ESP_ERR_NVS_NO_FREE_PAGES);
    CHECK(!GetStorageInitResult().available);
    network_fake::state.ssids.push_back({"saved-ap", "password", 1});
    const int initial_nvs_calls = network_fake::state.nvs_initializes;
    TestBoard board;
    std::vector<NetworkEvent> events;
    RecordEvents(board, events);
    board.StartNetwork();
    CHECK(network_fake::state.wifi_initializes == 0);
    CHECK(network_fake::state.nvs_initializes == initial_nvs_calls);
    CHECK(network_fake::state.nvs_erases == 0);
    CHECK(network_fake::state.ssid_reads == 0);
    CHECK(network_fake::state.station_starts == 0);
    CHECK(network_fake::state.ap_starts == 0);
    CHECK(network_fake::state.timer_starts == 0);
    CHECK(network_fake::state.delay_ms == 0);
    CHECK(events == std::vector<NetworkEvent>{NetworkEvent::Disconnected});
}

static void UnavailableStorageStaysOfflineForBothPolicies() {
    CheckUnavailableStorageSkipsManager<OfflineBoard>();
    CheckUnavailableStorageSkipsManager<LegacyBoard>();
}

static void ExplicitProvisioningRemainsAvailable() {
    ResetStorage();
    OfflineBoard board;
    board.StartNetwork();
    CHECK(network_fake::state.ap_starts == 0);
    board.EnterWifiConfigMode();
    CHECK(network_fake::state.ap_starts == 1);
    CHECK(board.IsInWifiConfigMode());
    CHECK(network_fake::state.nvs_erases == 0);
}

static void DelayedConfigExitCannotStopANewerAp() {
    ResetStorage();
    network_fake::state.ssids.push_back({"saved-ap", "password", 1});
    OfflineBoard board;
    board.StartNetwork();
    board.EnterWifiConfigMode();
    const int starts = network_fake::state.station_starts;
    network_fake::state.callback(WifiEvent::ConfigModeExit, "");
    CHECK(board.IsInWifiConfigMode());
    CHECK(network_fake::state.station_starts == starts);
    network_fake::state.ap_active = false;
    network_fake::state.callback(WifiEvent::ConfigModeExit, "");
    CHECK(!board.IsInWifiConfigMode());
    CHECK(network_fake::state.station_starts == starts + 1);
}

static void AirEventsRunOnApplicationTask() {
    ResetStorage();
    network_fake::state.queue_application = true;
    AirOfflineBoard board;
    int deliveries = 0;
    board.SetNetworkEventCallback([&](NetworkEvent, const std::string&) {
        CHECK(network_fake::state.application_running);
        ++deliveries;
    });
    board.StartNetwork();
    CHECK(deliveries == 0);
    CHECK(network_fake::state.application_queue.size() == 1);
    Application::GetInstance().Drain();
    CHECK(deliveries == 1);
    network_fake::state.station_active = true;
    network_fake::state.station_connected = true;
    network_fake::state.callback(WifiEvent::Connected, "network");
    CHECK(deliveries == 1);
    Application::GetInstance().Drain();
    CHECK(deliveries == 2);
}

static void AirExitCannotRaceNewApplicationAp() {
    ResetStorage();
    network_fake::state.queue_application = true;
    network_fake::state.ssids.push_back({"saved-ap", "password", 1});
    AirOfflineBoard board;
    board.StartNetwork();
    network_fake::state.station_active = false;
    network_fake::state.ap_active = false;
    // Simulate a new application request arriving immediately after IsConfigMode(false).
    network_fake::state.after_config_read = [&]() {
        auto& app = Application::GetInstance();
        app.Schedule([&]() { board.BeginConfig(); });
        // A main task may preempt a Wi-Fi worker, but cannot preempt itself.
        if (!network_fake::state.application_running)
            app.Drain();
    };
    network_fake::state.callback(WifiEvent::ConfigModeExit, "");
    Application::GetInstance().Drain();
    CHECK(network_fake::state.ap_active);
    CHECK(!network_fake::state.station_active);
    CHECK(board.IsInWifiConfigMode());
}

static void AirStaleConnectedCannotReactivateInApMode() {
    ResetStorage();
    network_fake::state.queue_application = true;
    network_fake::state.ssids.push_back({"saved-ap", "password", 1});
    AirOfflineBoard board;
    std::vector<NetworkEvent> events;
    RecordEvents(board, events);
    board.StartNetwork();
    network_fake::state.station_connected = true;
    network_fake::state.callback(WifiEvent::Connected, "previous-network");
    // The application is already in its manual configuration callback when the
    // old station event is queued. AP startup completes before it can be delivered.
    board.BeginConfig();
    Application::GetInstance().Drain();
    CHECK(network_fake::state.ap_active);
    CHECK(board.IsInWifiConfigMode());
    for (auto event : events)
        CHECK(event != NetworkEvent::Connected);
}

static void AirStaleEventsDoNotReplaceCurrentNetworkState() {
    ResetStorage();
    network_fake::state.queue_application = true;
    network_fake::state.ssids.push_back({"saved-ap", "password", 1});
    AirOfflineBoard board;
    std::vector<NetworkEvent> events;
    RecordEvents(board, events);
    board.StartNetwork();
    network_fake::state.station_connected = true;
    CHECK(board.IsNetworkConnected());
    // Every queued event now describes a state older than the current connection.
    network_fake::state.callback(WifiEvent::Disconnected, "15");
    network_fake::state.callback(WifiEvent::Scanning, "");
    network_fake::state.callback(WifiEvent::Connecting, "old-network");
    network_fake::state.callback(WifiEvent::ConfigModeEnter, "");
    Application::GetInstance().Drain();
    CHECK(events.empty());
    CHECK(!board.IsInWifiConfigMode());
}

int main(int argc, char** argv) {
    const struct {
        const char* name;
        void (*run)();
    } cases[] = {
        {"no_ssid_offline", NoSsidStaysOfflineWithoutProvisioning},
        {"legacy_no_ssid", LegacyNoSsidStillProvisions},
        {"timeout_offline", TimeoutKeepsStationWhenProvisioningDisabled},
        {"legacy_timeout", LegacyTimeoutStillProvisions},
        {"storage_offline", UnavailableStorageStaysOfflineForBothPolicies},
        {"explicit_provisioning", ExplicitProvisioningRemainsAvailable},
        {"late_config_exit", DelayedConfigExitCannotStopANewerAp},
        {"air_application_events", AirEventsRunOnApplicationTask},
        {"air_exit_race", AirExitCannotRaceNewApplicationAp},
        {"air_stale_connected", AirStaleConnectedCannotReactivateInApMode},
        {"air_stale_events", AirStaleEventsDoNotReplaceCurrentNetworkState},
    };
    int executed = 0;
    for (const auto& test : cases) {
        if (argc > 1 && std::strcmp(argv[1], test.name) != 0)
            continue;
        std::printf("wifi recovery: %s\n", test.name);
        std::fflush(stdout);
        test.run();
        ++executed;
    }
    CHECK(executed > 0);
    std::printf("wifi recovery: %d behavior tests passed\n", executed);
}
