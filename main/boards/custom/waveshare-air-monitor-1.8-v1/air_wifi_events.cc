#include "air_wifi_events.h"
#include <esp_log.h>
#include <wifi_manager.h>
#include <algorithm>

static_assert(static_cast<size_t>(WifiEvent::ConfigModeExit) == 5);

namespace air {
bool WifiEventMailbox::Publish(WifiEvent event, std::string_view data) {
    const auto index = static_cast<size_t>(event);
    if (index >= pending_.size())
        return false;
    std::lock_guard<std::mutex> lock(mutex_);
    auto& slot = pending_[index];
    slot.event = event;
    slot.size = std::min(data.size(), slot.data.size());
    std::copy_n(data.data(), slot.size, slot.data.data());
    slot.sequence = ++sequence_;
    return true;
}

bool WifiEventMailbox::Take(PendingWifiEvent& event) {
    std::lock_guard<std::mutex> lock(mutex_);
    PendingWifiEvent* first = nullptr;
    for (auto& slot : pending_)
        if (slot.sequence && (!first || slot.sequence < first->sequence))
            first = &slot;
    if (!first)
        return false;
    event = *first;
    first->sequence = 0;
    return true;
}

TaskHandle_t WifiEventDispatcher::EnsureWorker() {
    auto worker = worker_.load();
    if (worker || starting_.test_and_set())
        return worker;
    worker = worker_.load();
    if (!worker) {
        if (xTaskCreate([](void* context) { static_cast<WifiEventDispatcher*>(context)->Run(); },
                        "air_wifi_events", 4096, this, 3, &worker) == pdPASS)
            worker_.store(worker);
        else {
            worker = nullptr;
            ESP_LOGE("AirWiFi", "Event worker unavailable; pending WiFi states retained");
        }
    }
    starting_.clear();
    return worker;
}

bool WifiEventDispatcher::Publish(WifiEvent event, const std::string& data) {
    if (!mailbox_.Publish(event, data))
        return false;
    const auto worker = EnsureWorker();
    if (!worker)
        return false;
    xTaskNotifyGive(worker);
    return true;
}

void WifiEventDispatcher::Run() {
    while (true) {
        ulTaskNotifyTake(pdTRUE, portMAX_DELAY);
        PendingWifiEvent event;
        while (mailbox_.Take(event)) {
            const auto payload = event.Payload();
            delivery_(event.event, payload);
        }
    }
}
}  // namespace air
