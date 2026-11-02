#pragma once

enum class StorageInitPolicy { LegacyRecovery, PreserveOnFailure };
struct StorageInitResult {
    int error = 0;
    bool available = true;
    bool erased = false;
    StorageInitPolicy policy = StorageInitPolicy::LegacyRecovery;
};
struct NvsOperations {
    int (*initialize)();
    int (*erase)();
    bool (*recoverable)(int);
};
StorageInitResult InitializeNvsWithOps(StorageInitPolicy policy, const NvsOperations& ops);
StorageInitResult InitializeDefaultNvs(StorageInitPolicy policy);
StorageInitResult GetStorageInitResult();
void MarkStorageUnavailable(int error);
