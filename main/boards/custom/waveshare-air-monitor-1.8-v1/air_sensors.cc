#include "air_sensors.h"
#include <esp_timer.h>
#include "air_ha_upload.h"

namespace air {
bool AirSensors::Start(i2c_master_bus_handle_t bus, AirHaUpload* upload) {
    if (running_.exchange(true))
        return true;
    upload_ = upload;
    const uint8_t addresses[] = {0x62, 0x5D};
    for (size_t i = 0; i < 2; ++i) {
        i2c_device_config_t config{};
        config.dev_addr_length = I2C_ADDR_BIT_LEN_7;
        config.device_address = addresses[i];
        config.scl_speed_hz = 100000;
        if (i2c_master_bus_add_device(bus, &config, &devices_[i]) != ESP_OK) {
            running_ = false;
            return false;
        }
    }
    stopped_ = false;
    if (xTaskCreate([](void* ctx) { static_cast<AirSensors*>(ctx)->Run(); }, "air_sensors", 4096,
                    this, 2, &task_) != pdPASS) {
        running_ = false;
        stopped_ = true;
        return false;
    }
    return true;
}
void AirSensors::Stop() { running_ = false; }
bool AirSensors::Command(SensorId sensor, uint16_t command) {
    const uint8_t bytes[] = {static_cast<uint8_t>(command >> 8), static_cast<uint8_t>(command)};
    return i2c_master_transmit(devices_[static_cast<size_t>(sensor)], bytes, 2, 25) == ESP_OK;
}
bool AirSensors::Receive(SensorId sensor, uint8_t* bytes, size_t length) {
    return i2c_master_receive(devices_[static_cast<size_t>(sensor)], bytes, length, 25) == ESP_OK;
}
void AirSensors::Run() {
    uint64_t last_co2 = 0, last_hcho = 0;
    while (running_) {
        const uint64_t now = esp_timer_get_time() / 1000;
        schedule_.Tick(now);
        auto snapshot = model_.Snapshot(esp_timer_get_time() / 1000);
        if (upload_)
            upload_->Observe(snapshot);
        {
            // No bus transactions or LVGL calls while holding the publication lock.
            std::lock_guard<std::mutex> lock(mutex_);
            if (snapshot.co2.has_value && snapshot.co2.last_value_ms != last_co2) {
                history_[0] = model_.History(Metric::Co2);
                last_co2 = snapshot.co2.last_value_ms;
            }
            if (snapshot.hcho.has_value && snapshot.hcho.last_value_ms != last_hcho) {
                history_[1] = model_.History(Metric::Hcho);
                last_hcho = snapshot.hcho.last_value_ms;
            }
            published_ = snapshot;
        }
        vTaskDelay(pdMS_TO_TICKS(10));
    }
    if (upload_)
        upload_->FinishCollection(esp_timer_get_time() / 1000);
    Command(SensorId::Scd41, 0x3F86);
    Command(SensorId::Sfa40, 0x50D2);
    stopped_ = true;
    vTaskDelete(nullptr);
}
AirSnapshot AirSensors::Snapshot() const {
    std::lock_guard<std::mutex> lock(mutex_);
    auto snapshot = published_;
    snapshot.now_ms = esp_timer_get_time() / 1000;
    snapshot.co2.stale =
        snapshot.co2.has_value && snapshot.now_ms - snapshot.co2.last_value_ms > 15000;
    snapshot.hcho.stale =
        snapshot.hcho.has_value && snapshot.now_ms - snapshot.hcho.last_value_ms > 5000;
    return snapshot;
}
void AirSensors::CopyHistory(Metric metric, std::array<HistoryPoint, kHistorySize>& out) const {
    std::lock_guard<std::mutex> lock(mutex_);
    out = history_[static_cast<size_t>(metric)];
}
}  // namespace air
