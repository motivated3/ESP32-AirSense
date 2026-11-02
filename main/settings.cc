#include "settings.h"
#include "storage_init.h"

#include <esp_log.h>
#include <nvs_flash.h>

#define TAG "Settings"

Settings::Settings(const std::string& ns, bool read_write) : ns_(ns), read_write_(read_write) {
    const auto storage = GetStorageInitResult();
    if (storage.policy == StorageInitPolicy::PreserveOnFailure && !storage.available)
        return;
    auto error = nvs_open(ns.c_str(), read_write_ ? NVS_READWRITE : NVS_READONLY, &nvs_handle_);
    if (error != ESP_OK) {
        nvs_handle_ = 0;
        if (read_write_ && storage.policy == StorageInitPolicy::PreserveOnFailure)
            HandleResult(error);
    }
}

bool Settings::CanWrite() const {
    return read_write_ && nvs_handle_ != 0 && GetStorageInitResult().available;
}

bool Settings::HandleResult(esp_err_t error) {
    if (error == ESP_OK)
        return true;
    if (GetStorageInitResult().policy == StorageInitPolicy::PreserveOnFailure) {
        MarkStorageUnavailable(error);
        dirty_ = false;
        ESP_LOGE(TAG, "NVS error %d; retaining flash and disabling writes", error);
        return false;
    }
    ESP_ERROR_CHECK(error);
    return false;
}

Settings::~Settings() {
    if (nvs_handle_ != 0) {
        if (CanWrite() && dirty_) {
            HandleResult(nvs_commit(nvs_handle_));
        }
        nvs_close(nvs_handle_);
    }
}

std::string Settings::GetString(const std::string& key, const std::string& default_value) {
    if (nvs_handle_ == 0) {
        return default_value;
    }

    size_t length = 0;
    if (nvs_get_str(nvs_handle_, key.c_str(), nullptr, &length) != ESP_OK) {
        return default_value;
    }

    std::string value;
    value.resize(length);
    if (!HandleResult(nvs_get_str(nvs_handle_, key.c_str(), value.data(), &length)))
        return default_value;
    while (!value.empty() && value.back() == '\0') {
        value.pop_back();
    }
    return value;
}

void Settings::SetString(const std::string& key, const std::string& value) {
    if (CanWrite()) {
        if (HandleResult(nvs_set_str(nvs_handle_, key.c_str(), value.c_str())))
            dirty_ = true;
    } else {
        ESP_LOGW(TAG, "Namespace %s is not open for writing", ns_.c_str());
    }
}

int32_t Settings::GetInt(const std::string& key, int32_t default_value) {
    if (nvs_handle_ == 0) {
        return default_value;
    }

    int32_t value;
    if (nvs_get_i32(nvs_handle_, key.c_str(), &value) != ESP_OK) {
        return default_value;
    }
    return value;
}

void Settings::SetInt(const std::string& key, int32_t value) {
    if (CanWrite()) {
        if (HandleResult(nvs_set_i32(nvs_handle_, key.c_str(), value)))
            dirty_ = true;
    } else {
        ESP_LOGW(TAG, "Namespace %s is not open for writing", ns_.c_str());
    }
}

bool Settings::GetBool(const std::string& key, bool default_value) {
    if (nvs_handle_ == 0) {
        return default_value;
    }

    uint8_t value;
    if (nvs_get_u8(nvs_handle_, key.c_str(), &value) != ESP_OK) {
        return default_value;
    }
    return value != 0;
}

void Settings::SetBool(const std::string& key, bool value) {
    if (CanWrite()) {
        if (HandleResult(nvs_set_u8(nvs_handle_, key.c_str(), value ? 1 : 0)))
            dirty_ = true;
    } else {
        ESP_LOGW(TAG, "Namespace %s is not open for writing", ns_.c_str());
    }
}

void Settings::EraseKey(const std::string& key) {
    if (CanWrite()) {
        auto ret = nvs_erase_key(nvs_handle_, key.c_str());
        if (ret != ESP_ERR_NVS_NOT_FOUND) {
            HandleResult(ret);
        }
    } else {
        ESP_LOGW(TAG, "Namespace %s is not open for writing", ns_.c_str());
    }
}

void Settings::EraseAll() {
    if (CanWrite()) {
        HandleResult(nvs_erase_all(nvs_handle_));
    } else {
        ESP_LOGW(TAG, "Namespace %s is not open for writing", ns_.c_str());
    }
}
