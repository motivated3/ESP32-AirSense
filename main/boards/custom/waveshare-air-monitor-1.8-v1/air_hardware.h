#pragma once
#include <driver/i2c_master.h>
#include <atomic>
#include <functional>
#include <mutex>
#include "air_controls.h"
#include "air_types.h"
#include "shutdown_coordinator.h"

namespace air {
class AirHardware {
public:
    bool Initialize(i2c_master_bus_handle_t bus);
    bool Start(std::function<void(ButtonAction)> on_action, std::function<void()> on_shutdown,
               std::function<ShutdownProgress()> shutdown_progress);
    void RequestShutdown();
    bool IsShuttingDown() const { return shutdown_.load(); }
    void SetDisplayOn(bool on) { display_on_ = on; }
    PowerSnapshot Snapshot() const;

private:
    bool Read(i2c_master_dev_handle_t device, uint8_t reg, uint8_t* bytes, size_t size);
    bool Write(i2c_master_dev_handle_t device, uint8_t reg, uint8_t value);
    bool ModifyPmic(uint8_t reg, uint8_t mask, uint8_t value);
    bool PowerOff();
    void Run();
    i2c_master_dev_handle_t pmic_ = nullptr;
    i2c_master_dev_handle_t expander_ = nullptr;
    InputPolicy input_;
    DebouncedInput debounce_[2];
    mutable std::mutex mutex_;
    PowerSnapshot power_;
    std::atomic<bool> display_on_{true};
    std::atomic<bool> shutdown_{false};
    std::function<void(ButtonAction)> on_action_;
    std::function<void()> on_shutdown_;
    std::function<ShutdownProgress()> shutdown_progress_;
};
}  // namespace air
