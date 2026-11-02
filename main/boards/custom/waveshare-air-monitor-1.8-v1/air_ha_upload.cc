#include "air_ha_upload.h"
#include <esp_crt_bundle.h>
#include <esp_heap_caps.h>
#include <esp_http_client.h>
#include <esp_log.h>
#include <esp_random.h>
#include <esp_timer.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include <strings.h>
#include <wifi_manager.h>
#include <algorithm>
#include <cstdio>
#include <cstring>
#include <new>
#include "air_ha_credentials.h"
#include "air_ha_protocol.h"

namespace air {
namespace {
constexpr const char* kTag = "AirHaUpload";
uint64_t Now() { return esp_timer_get_time() / 1000; }
struct Response {
    std::string body, date;
    int status = 0;
    bool ok = false;
    bool bounded = true;
};
esp_err_t OnHttp(esp_http_client_event_t* event) {
    auto& response = *static_cast<Response*>(event->user_data);
    if (event->event_id == HTTP_EVENT_ON_HEADER && event->header_key && event->header_value &&
        strcasecmp(event->header_key, "Date") == 0) {
        if (strlen(event->header_value) > 64) {
            response.bounded = false;
            return ESP_FAIL;
        }
        response.date = event->header_value;
    }
    if (event->event_id == HTTP_EVENT_ON_DATA && event->data_len > 0) {
        if (response.body.size() + event->data_len > 4096) {
            response.bounded = false;
            return ESP_FAIL;
        }
        response.body.append(static_cast<const char*>(event->data), event->data_len);
    }
    return ESP_OK;
}
Response Request(const std::string* body, int timeout_ms) {
    Response response;
    esp_http_client_config_t config{};
    config.url = ha_config::kEndpoint;
    config.method = body ? HTTP_METHOD_POST : HTTP_METHOD_HEAD;
    config.timeout_ms = timeout_ms;
    config.disable_auto_redirect = true;
    config.crt_bundle_attach = esp_crt_bundle_attach;
    config.event_handler = OnHttp;
    config.user_data = &response;
    const auto client = esp_http_client_init(&config);
    if (!client)
        return response;
    bool configured = true;
    if (body) {
        const std::string authorization = std::string("Bearer ") + ha_config::kKey;
        configured =
            esp_http_client_set_header(client, "Content-Type", "application/json") == ESP_OK &&
            esp_http_client_set_header(client, "X-Air-Monitor-Device", ha_config::kDevice) ==
                ESP_OK &&
            esp_http_client_set_header(client, "Authorization", authorization.c_str()) == ESP_OK &&
            esp_http_client_set_post_field(client, body->data(), body->size()) == ESP_OK;
    }
    if (configured) {
        const auto result = esp_http_client_perform(client);
        response.ok = result == ESP_OK && response.bounded;
        response.status = esp_http_client_get_status_code(client);
    }
    esp_http_client_cleanup(client);
    return response;
}
}  // namespace

bool AirHaUpload::Start(SolarUpdate solar_update) {
    if (!ha_config::kEnabled) {
        ESP_LOGW(kTag, "Disabled: no private HA credential configuration");
        return true;
    }
    void* storage = heap_caps_malloc(sizeof(HaMinuteBuffer), MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    if (!storage)
        storage = heap_caps_malloc(sizeof(HaMinuteBuffer), MALLOC_CAP_8BIT);
    if (!storage)
        return false;
    buffer_ = new (storage) HaMinuteBuffer;
    solar_update_ = std::move(solar_update);
    stopped_ = false;
    if (xTaskCreate([](void* context) { static_cast<AirHaUpload*>(context)->Run(); }, "air_ha",
                    12288, this, 1, nullptr) != pdPASS) {
        stopped_ = true;
        buffer_->~HaMinuteBuffer();
        heap_caps_free(buffer_);
        buffer_ = nullptr;
        return false;
    }
    ESP_LOGI(kTag, "Enabled: 60-second records, %u-record RAM queue",
             unsigned(HaMinuteBuffer::kCapacity));
    return true;
}

void AirHaUpload::Observe(const AirSnapshot& snapshot) {
    if (!buffer_)
        return;
    std::lock_guard<std::mutex> lock(mutex_);
    buffer_->Observe(snapshot);
}

void AirHaUpload::FinishCollection(uint64_t now_ms) {
    if (buffer_) {
        std::lock_guard<std::mutex> lock(mutex_);
        buffer_->Flush(now_ms);
    }
    collection_done_ = true;
}

void AirHaUpload::Stop() {
    shutdown_ms_ = Now();
    stop_ = true;
}

void AirHaUpload::Run() {
    char session[48];
    std::snprintf(
        session, sizeof(session), "boot-%08lx%08lx%08lx%08lx",
        static_cast<unsigned long>(esp_random()), static_cast<unsigned long>(esp_random()),
        static_cast<unsigned long>(esp_random()), static_cast<unsigned long>(esp_random()));
    HaBatch flight;
    HaUtcClock clock;
    HaRetry retry;
    bool was_connected = false;
    uint64_t synchronized_ms = 0;
    uint32_t reported_dropped = 0;
    while (true) {
        const uint64_t now = Now();
        const bool stopping = stop_.load();
        if (stopping && !collection_done_) {
            vTaskDelay(pdMS_TO_TICKS(10));
            continue;
        }
        const bool connected =
            WifiManager::GetInstance().IsConnected() && !WifiManager::GetInstance().IsConfigMode();
        if (connected && !was_connected)
            retry.Reconnected(now);
        was_connected = connected;
        bool pending;
        size_t queued;
        uint32_t dropped;
        {
            std::lock_guard<std::mutex> lock(mutex_);
            pending = flight.Capture(*buffer_);
            queued = buffer_->size();
            dropped = buffer_->dropped();
        }
        if (dropped != reported_dropped) {
            ESP_LOGW(kTag, "RAM queue full: %lu new minute records dropped",
                     static_cast<unsigned long>(dropped));
            reported_dropped = dropped;
        }
        const uint64_t elapsed_shutdown = stopping ? now - shutdown_ms_.load() : 0;
        if (stopping && (!pending || !connected || !clock.synced() || elapsed_shutdown >= 700))
            break;
        if (connected && pending && (stopping || retry.Due(now))) {
            if (!clock.synced() || (!stopping && now - synchronized_ms >= 3600000)) {
                const auto response = Request(nullptr, 5000);
                if (response.ok &&
                    (response.status == 200 || response.status == 401 || response.status == 405) &&
                    clock.Synchronize(response.date, Now())) {
                    synchronized_ms = Now();
                    retry.Reconnected(Now());
                } else {
                    ESP_LOGW(kTag, "UTC synchronization failed (HTTP %d); %u records retained",
                             response.status, unsigned(queued));
                    retry.Failure(Now(), esp_random() % 1001);
                }
            } else if (flight.Encode(ha_config::kDevice, session, clock)) {
                const auto response = Request(
                    &flight.body(), stopping ? std::max(1, 700 - int(elapsed_shutdown)) : 5000);
                if (response.ok && response.status == 200 &&
                    flight.CheckAck(response.body, ha_config::kDevice, session)) {
                    const auto received_ms = Now();
                    const auto utc_ms = clock.ToEpochMs(received_ms);
                    if (solar_update_ && utc_ms && !stopping)
                        solar_update_(ParseHaSolarLocation(response.body), *utc_ms, received_ms);
                    std::lock_guard<std::mutex> lock(mutex_);
                    flight.Commit(*buffer_);
                    retry.Success(Now());
                } else {
                    ESP_LOGW(kTag, "Upload unconfirmed (HTTP %d); %u records retained",
                             response.status, unsigned(queued));
                    retry.Failure(Now(), esp_random() % 1001);
                }
            } else {
                ESP_LOGW(kTag, "Could not encode upload; records retained");
                retry.Failure(Now(), esp_random() % 1001);
            }
            if (stopping)
                break;
        }
        vTaskDelay(pdMS_TO_TICKS(250));
    }
    stopped_ = true;
    vTaskDelete(nullptr);
}
}  // namespace air
