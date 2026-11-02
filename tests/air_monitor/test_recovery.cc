#include <initializer_list>
#include "storage_init.h"
#include "test_support.h"

static int init_calls, erase_calls, first_error, erase_error;
static int Init() { return ++init_calls == 1 ? first_error : 0; }
static int Erase() {
    ++erase_calls;
    return erase_error;
}
static bool Recoverable(int error) { return error == 100 || error == 101; }
static void Reset(int error) {
    init_calls = erase_calls = erase_error = 0;
    first_error = error;
}
int main() {
    const NvsOperations ops{Init, Erase, Recoverable};
    for (int error : {100, 101, 999}) {
        Reset(error);
        auto result = InitializeNvsWithOps(StorageInitPolicy::PreserveOnFailure, ops);
        CHECK(!result.available && !result.erased && result.error == error);
        CHECK(init_calls == 1 && erase_calls == 0);
    }
    Reset(100);
    auto legacy = InitializeNvsWithOps(StorageInitPolicy::LegacyRecovery, ops);
    CHECK(legacy.available && legacy.erased && legacy.error == 0);
    CHECK(init_calls == 2 && erase_calls == 1);
    Reset(100);
    erase_error = 55;
    auto failed = InitializeNvsWithOps(StorageInitPolicy::LegacyRecovery, ops);
    CHECK(!failed.available && !failed.erased && failed.error == 55);
    Reset(0);
    CHECK(InitializeNvsWithOps(StorageInitPolicy::PreserveOnFailure, ops).available);
    CHECK(erase_calls == 0);
    std::puts("storage: preserve-on-failure and legacy recovery passed");
}
