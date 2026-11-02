#include "settings.h"
#include "storage_init.h"
#include "test_support.h"

static int init_error = 0, write_error = 0, opens = 0, writes = 0, commits = 0, erases = 0;
int nvs_flash_init() { return init_error; }
int nvs_flash_erase() {
    ++erases;
    return 0;
}
int nvs_open(const char*, int, nvs_handle_t* handle) {
    ++opens;
    *handle = 42;
    return 0;
}
void nvs_close(nvs_handle_t) {}
int nvs_commit(nvs_handle_t) {
    ++commits;
    return write_error;
}
int nvs_get_str(nvs_handle_t, const char*, char*, size_t*) { return ESP_ERR_NVS_NOT_FOUND; }
int nvs_get_i32(nvs_handle_t, const char*, int32_t*) { return ESP_ERR_NVS_NOT_FOUND; }
int nvs_get_u8(nvs_handle_t, const char*, uint8_t*) { return ESP_ERR_NVS_NOT_FOUND; }
int nvs_set_str(nvs_handle_t, const char*, const char*) {
    ++writes;
    return write_error;
}
int nvs_set_i32(nvs_handle_t, const char*, int32_t) {
    ++writes;
    return write_error;
}
int nvs_set_u8(nvs_handle_t, const char*, uint8_t) {
    ++writes;
    return write_error;
}
int nvs_erase_key(nvs_handle_t, const char*) {
    ++writes;
    return write_error;
}
int nvs_erase_all(nvs_handle_t) {
    ++writes;
    return write_error;
}
int main() {
    init_error = ESP_ERR_NVS_NO_FREE_PAGES;
    InitializeDefaultNvs(StorageInitPolicy::PreserveOnFailure);
    {
        Settings offline("board", true);
        CHECK(opens == 0);
        CHECK(offline.GetString("uuid", "fallback") == "fallback");
        offline.SetString("uuid", "transient");
        offline.SetInt("brightness", 70);
        offline.SetBool("voice", true);
        offline.EraseAll();
        offline.EraseKey("ssid");
    }
    CHECK(writes == 0 && commits == 0 && erases == 0);
    init_error = 0;
    InitializeDefaultNvs(StorageInitPolicy::PreserveOnFailure);
    {
        Settings normal("air", true);
        normal.SetInt("day", 80);
    }
    CHECK(writes == 1 && commits == 1);
    write_error = 77;
    {
        Settings failed("air", true);
        failed.SetInt("day", 90);
        CHECK(!GetStorageInitResult().available);
    }
    CHECK(commits == 1 && erases == 0);
    std::puts(
        "settings: failed storage never writes, healthy commit retained, runtime error stays "
        "offline passed");
}
