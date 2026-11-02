#pragma once
#include <wifi_manager.h>
#include "../../common/wifi_board.h"
#include "application.h"

namespace air {
class AirWifiBoard : public WifiBoard {
public:
    bool IsNetworkConnected() const override { return WifiManager::GetInstance().IsConnected(); }

protected:
    void OnNetworkEvent(NetworkEvent event, const std::string& data = "") override {
        // Serialize reconnect decisions with the AIR board's manual AP controls.
        Application::GetInstance().Schedule([this, event, data]() {
            auto& wifi = WifiManager::GetInstance();
            switch (event) {
                case NetworkEvent::Connected:
                    if (!wifi.IsConnected())
                        return;
                    break;
                case NetworkEvent::Disconnected:
                case NetworkEvent::Scanning:
                    if (wifi.IsConnected())
                        return;
                    break;
                case NetworkEvent::Connecting:
                    if (wifi.IsConnected() || wifi.IsConfigMode())
                        return;
                    break;
                case NetworkEvent::WifiConfigModeEnter:
                    if (!wifi.IsConfigMode())
                        return;
                    break;
                default:
                    break;
            }
            WifiBoard::OnNetworkEvent(event, data);
        });
    }
};
}  // namespace air
