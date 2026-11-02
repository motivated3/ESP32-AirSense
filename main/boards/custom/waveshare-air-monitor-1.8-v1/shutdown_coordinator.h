#pragma once
#include <cstdint>
namespace air {
struct ShutdownProgress {
    bool audio_stopped = false;
    bool sensors_stopped = false;
    bool preferences_flushed = false;
};
enum class PowerOffTrigger { None, Prepared, Timeout };
class ShutdownCoordinator {
public:
    void Request(uint64_t now_ms) {
        if (!requested_) {
            requested_ = true;
            deadline_ = now_ms + 1200;
        }
    }
    PowerOffTrigger Poll(uint64_t now_ms, const ShutdownProgress& progress) {
        if (!requested_ || now_ms < retry_due_)
            return PowerOffTrigger::None;
        const bool ready =
            progress.audio_stopped && progress.sensors_stopped && progress.preferences_flushed;
        if (!ready && now_ms < deadline_)
            return PowerOffTrigger::None;
        retry_due_ = now_ms + 1000;
        return ready ? PowerOffTrigger::Prepared : PowerOffTrigger::Timeout;
    }

private:
    bool requested_ = false;
    uint64_t deadline_ = 0, retry_due_ = 0;
};
}  // namespace air
