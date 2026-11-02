#include <driver/gpio.h>
#include <esp_err.h>
#include <esp_event.h>
#include <esp_log.h>
#include <esp_system.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include <nvs.h>
#include <nvs_flash.h>

#include "application.h"
#include "storage_init.h"

#define TAG "main"

extern "C" void app_main(void)
{
    // Initialize NVS flash for WiFi configuration
#ifdef CONFIG_PRESERVE_NVS_ON_INIT_FAILURE
    const auto storage = InitializeDefaultNvs(StorageInitPolicy::PreserveOnFailure);
    if (!storage.available)
        ESP_LOGE(TAG, "NVS unavailable (%d); retaining flash and starting offline", storage.error);
#else
    const auto storage = InitializeDefaultNvs(StorageInitPolicy::LegacyRecovery);
    ESP_ERROR_CHECK(storage.error);
#endif
    ESP_LOGI(TAG, "Reset reason: %d", esp_reset_reason());

    // Initialize and run the application
    auto& app = Application::GetInstance();
    app.Initialize();
    app.Run();  // This function runs the main event loop and never returns
}
