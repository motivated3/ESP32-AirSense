#pragma once
#include <cstddef>
#include <cstdint>
using nvs_handle_t = uint32_t;
using esp_err_t = int;
constexpr int ESP_OK = 0;
constexpr int ESP_ERR_NVS_NO_FREE_PAGES = 0x110D;
constexpr int ESP_ERR_NVS_NEW_VERSION_FOUND = 0x1110;
constexpr int ESP_ERR_NVS_NOT_FOUND = 0x1102;
constexpr int NVS_READWRITE = 1, NVS_READONLY = 0;
int nvs_flash_init();
int nvs_flash_erase();
int nvs_open(const char*, int, nvs_handle_t*);
void nvs_close(nvs_handle_t);
int nvs_commit(nvs_handle_t);
int nvs_get_str(nvs_handle_t, const char*, char*, size_t*);
int nvs_get_i32(nvs_handle_t, const char*, int32_t*);
int nvs_get_u8(nvs_handle_t, const char*, uint8_t*);
int nvs_set_str(nvs_handle_t, const char*, const char*);
int nvs_set_i32(nvs_handle_t, const char*, int32_t);
int nvs_set_u8(nvs_handle_t, const char*, uint8_t);
int nvs_erase_key(nvs_handle_t, const char*);
int nvs_erase_all(nvs_handle_t);
