#include "shutdown_coordinator.h"
#include "test_support.h"
using namespace air;
int main() {
    ShutdownCoordinator normal;
    CHECK(normal.Poll(100, {true, true, true}) == PowerOffTrigger::None);
    normal.Request(100);
    CHECK(normal.Poll(200, {true, true, false}) == PowerOffTrigger::None);
    CHECK(normal.Poll(300, {true, false, true}) == PowerOffTrigger::None);
    CHECK(normal.Poll(400, {false, true, true}) == PowerOffTrigger::None);
    CHECK(normal.Poll(500, {true, true, true}) == PowerOffTrigger::Prepared);
    // A failed PMIC write can retry, without a second preparation or busy-loop.
    CHECK(normal.Poll(1499, {true, true, true}) == PowerOffTrigger::None);
    CHECK(normal.Poll(1500, {true, true, true}) == PowerOffTrigger::Prepared);
    ShutdownCoordinator blocked;
    blocked.Request(100);
    blocked.Request(1200);  // A duplicate must not postpone the fallback deadline.
    CHECK(blocked.Poll(1299, {}) == PowerOffTrigger::None);
    CHECK(blocked.Poll(1300, {}) == PowerOffTrigger::Timeout);
    CHECK(blocked.Poll(2299, {}) == PowerOffTrigger::None);
    CHECK(blocked.Poll(2300, {}) == PowerOffTrigger::Timeout);
    std::puts(
        "shutdown: ordered completion, duplicate requests, timeout and bounded retries passed");
}
