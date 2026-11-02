#pragma once
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include <array>
#include <atomic>
#include <cstdint>
#include <functional>
#include <mutex>
#include <string>
#include <string_view>
#include <utility>

enum class WifiEvent;

namespace air {
struct PendingWifiEvent {
    WifiEvent event{};
    std::array<char, 32> data{};
    uint8_t size = 0;
    uint64_t sequence = 0;
    std::string Payload() const { return {data.data(), size}; }
};

// One pending value per event kind; replacing a kind also updates its order.
class WifiEventMailbox {
public:
    bool Publish(WifiEvent event, std::string_view data);
    bool Take(PendingWifiEvent& event);

private:
    std::mutex mutex_;
    std::array<PendingWifiEvent, 6> pending_{};
    uint64_t sequence_ = 0;
};

// Owned by the process-lifetime WifiManager singleton's NotifyEvent function.
class WifiEventDispatcher {
public:
    using Delivery = std::function<void(WifiEvent, const std::string&)>;
    explicit WifiEventDispatcher(Delivery delivery) : delivery_(std::move(delivery)) {}
    bool Publish(WifiEvent event, const std::string& data);

private:
    TaskHandle_t EnsureWorker();
    void Run();
    WifiEventMailbox mailbox_;
    const Delivery delivery_;
    std::atomic<TaskHandle_t> worker_{nullptr};
    std::atomic_flag starting_ = ATOMIC_FLAG_INIT;
};
}  // namespace air
