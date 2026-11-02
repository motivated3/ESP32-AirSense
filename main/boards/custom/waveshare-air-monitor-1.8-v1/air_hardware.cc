#include "air_hardware.h"
#include <esp_log.h>
#include <esp_timer.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include "config.h"

namespace air {
static constexpr const char* kTag = "AirPower";
bool AirHardware::Read(i2c_master_dev_handle_t device, uint8_t reg, uint8_t* bytes, size_t size) {
    return i2c_master_transmit_receive(device, &reg, 1, bytes, size, 25) == ESP_OK;
}
bool AirHardware::Write(i2c_master_dev_handle_t device, uint8_t reg, uint8_t value) {
    const uint8_t bytes[] = {reg, value};
    return i2c_master_transmit(device, bytes, 2, 25) == ESP_OK;
}
bool AirHardware::ModifyPmic(uint8_t reg, uint8_t mask, uint8_t value) {
    uint8_t old = 0, actual = 0;
    if (!Read(pmic_, reg, &old, 1))
        return false;
    const uint8_t next = (old & ~mask) | (value & mask);
    return Write(pmic_, reg, next) && Read(pmic_, reg, &actual, 1) &&
           (actual & mask) == (next & mask);
}
bool AirHardware::Initialize(i2c_master_bus_handle_t bus) {
    i2c_device_config_t config{};
    config.dev_addr_length = I2C_ADDR_BIT_LEN_7;
    config.scl_speed_hz = 400000;
    config.device_address = 0x34;
    if (i2c_master_bus_add_device(bus, &config, &pmic_) != ESP_OK)
        return false;
    config.device_address = 0x20;
    if (i2c_master_bus_add_device(bus, &config, &expander_) != ESP_OK)
        return false;
    // This service is the sole register owner; no separate TCA cached-output driver.
    if (!Write(expander_, 0x02, 0x00) || !Write(expander_, 0x03, 0xF8) ||
        !Write(expander_, 0x01, 0xFF))
        return false;
    vTaskDelay(pdMS_TO_TICKS(100));
    if (!Write(expander_, 0x01, 0xF8))
        return false;
    vTaskDelay(pdMS_TO_TICKS(300));
    if (!Write(expander_, 0x01, 0xFF))
        return false;
    // Unknown battery: disable both charging paths; preserve fuel gauge/watchdog bits.
    if (!ModifyPmic(0x18, 0x06, 0) || !ModifyPmic(0x22, 0x07, 0x06) ||
        !ModifyPmic(0x27, 0x0C, 0x04) || !ModifyPmic(0x82, 0x1F, 0x12) ||
        !ModifyPmic(0x80, 0x01, 0x01) || !ModifyPmic(0x92, 0x1F, 0x1C) ||
        !ModifyPmic(0x90, 0x01, 0x01))
        return false;
    gpio_config_t gpio{};
    gpio.pin_bit_mask = 1ULL << BOOT_BUTTON_GPIO;
    gpio.mode = GPIO_MODE_INPUT;
    gpio.pull_up_en = GPIO_PULLUP_ENABLE;
    return gpio_config(&gpio) == ESP_OK;
}
bool AirHardware::Start(std::function<void(ButtonAction)> on_action,
                        std::function<void()> on_shutdown,
                        std::function<ShutdownProgress()> shutdown_progress) {
    on_action_ = std::move(on_action);
    on_shutdown_ = std::move(on_shutdown);
    shutdown_progress_ = std::move(shutdown_progress);
    return xTaskCreate([](void* ctx) { static_cast<AirHardware*>(ctx)->Run(); }, "air_input", 4096,
                       this, 3, nullptr) == pdPASS;
}
void AirHardware::RequestShutdown() { shutdown_ = true; }
bool AirHardware::PowerOff() {
    uint8_t value;
    return Read(pmic_, 0x10, &value, 1) && Write(pmic_, 0x10, value | 1);
}
PowerSnapshot AirHardware::Snapshot() const {
    std::lock_guard<std::mutex> lock(mutex_);
    auto result = power_;
    result.display_on = display_on_;
    result.shutting_down = shutdown_;
    return result;
}
void AirHardware::Run() {
    uint64_t power_due = 0;
    ShutdownCoordinator coordinator;
    bool notified = false;
    while (true) {
        const uint64_t now = esp_timer_get_time() / 1000;
        if (shutdown_) {
            if (!notified) {
                notified = true;
                coordinator.Request(now);
                ESP_LOGI(kTag, "Graceful shutdown requested");
                if (on_shutdown_)
                    on_shutdown_();
            }
            const auto trigger = coordinator.Poll(now, shutdown_progress_());
            if (trigger != PowerOffTrigger::None) {
                if (trigger == PowerOffTrigger::Timeout)
                    ESP_LOGW(kTag,
                             "Shutdown preparation timed out; using bounded power-off fallback");
                if (!PowerOff())
                    ESP_LOGE(kTag,
                             "PMIC off failed; hardware long-press fallback remains available");
            }
            vTaskDelay(pdMS_TO_TICKS(20));
            continue;
        }
        uint8_t pins = 0;
        const bool valid = Read(expander_, 0, &pins, 1);
        const uint64_t sampled_at = esp_timer_get_time() / 1000;
        const bool raw[] = {gpio_get_level(BOOT_BUTTON_GPIO) == 0, (pins & 0x10) != 0};
        for (size_t i = 0; i < 2; ++i) {
            const auto stable = debounce_[i].Update(raw[i], sampled_at, i == 0 || valid);
            const auto action = input_.Update(static_cast<ButtonId>(i), stable.value_or(false),
                                              sampled_at, stable.has_value());
            if (action == ButtonAction::Shutdown)
                RequestShutdown();
            else if (action != ButtonAction::None && on_action_)
                on_action_(action);
        }
        if (now >= power_due) {
            uint8_t status[2] = {}, percent = 0;
            PowerSnapshot next;
            next.valid = Read(pmic_, 0, status, 2);
            if (next.valid) {
                next.vbus = (status[0] & 0x20) != 0;
                next.battery_present = (status[0] & 0x08) != 0;
                const auto direction = (status[1] >> 5) & 3;
                next.charging = next.battery_present && direction == 1;
                next.discharging = next.battery_present && direction == 2;
                if (next.battery_present && Read(pmic_, 0xA4, &percent, 1) && percent <= 100)
                    next.battery_percent = percent;
            }
            {
                std::lock_guard<std::mutex> lock(mutex_);
                power_ = next;
            }
            power_due = now + 1000;
        }
        vTaskDelay(pdMS_TO_TICKS(20));
    }
}
}  // namespace air
