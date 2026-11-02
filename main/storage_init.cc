#include "storage_init.h"
#include <atomic>
#ifdef ESP_PLATFORM
#include <nvs_flash.h>
#endif

namespace {
std::atomic<int> last_error{0};
std::atomic<bool> available{true};
std::atomic<bool> erased{false};
std::atomic<StorageInitPolicy> current_policy{StorageInitPolicy::LegacyRecovery};
}  // namespace
StorageInitResult InitializeNvsWithOps(StorageInitPolicy policy, const NvsOperations& ops) {
    StorageInitResult result;
    result.policy = policy;
    result.error = ops.initialize();
    if (result.error && policy == StorageInitPolicy::LegacyRecovery &&
        ops.recoverable(result.error)) {
        result.error = ops.erase();
        if (!result.error) {
            result.erased = true;
            result.error = ops.initialize();
        }
    }
    result.available = result.error == 0;
    return result;
}
StorageInitResult InitializeDefaultNvs(StorageInitPolicy policy) {
#ifdef ESP_PLATFORM
    const NvsOperations ops{nvs_flash_init, nvs_flash_erase, [](int error) {
                                return error == ESP_ERR_NVS_NO_FREE_PAGES ||
                                       error == ESP_ERR_NVS_NEW_VERSION_FOUND;
                            }};
    const auto result = InitializeNvsWithOps(policy, ops);
    current_policy = policy;
    last_error = result.error;
    available = result.available;
    erased = result.erased;
    return result;
#else
    (void)policy;
    return GetStorageInitResult();
#endif
}
StorageInitResult GetStorageInitResult() {
    return {last_error.load(), available.load(), erased.load(), current_policy.load()};
}
void MarkStorageUnavailable(int error) {
    last_error = error;
    available = false;
}
