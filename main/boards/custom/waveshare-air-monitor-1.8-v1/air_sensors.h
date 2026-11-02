#pragma once
#include <driver/i2c_master.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include <atomic>
#include <mutex>
#include "sensor_schedule.h"

namespace air {
class AirHaUpload;
class AirSensors : private SensorBus {
public:
    bool Start(i2c_master_bus_handle_t bus, AirHaUpload* upload = nullptr);
    void Stop();
    bool stopped() const { return stopped_.load(); }
    AirSnapshot Snapshot() const;
    void CopyHistory(Metric metric, std::array<HistoryPoint, kHistorySize>& out) const;

private:
    AirHaUpload* upload_ = nullptr;
    bool Command(SensorId sensor, uint16_t command) override;
    bool Receive(SensorId sensor, uint8_t* bytes, size_t length) override;
    void Run();
    i2c_master_dev_handle_t devices_[2]{};
    AirModel model_;
    SensorSchedule schedule_{*this, model_};
    mutable std::mutex mutex_;
    AirSnapshot published_;
    std::array<HistoryPoint, kHistorySize> history_[2]{};
    std::atomic<bool> running_{false};
    std::atomic<bool> stopped_{true};
    TaskHandle_t task_ = nullptr;
};
}  // namespace air
