#pragma once
#include <atomic>
#include <functional>
#include <mutex>
#include "air_ha_model.h"
#include "air_solar_theme.h"

namespace air {
class AirHaUpload {
public:
    using SolarUpdate = std::function<void(std::optional<SolarLocation>, int64_t, uint64_t)>;
    bool Start(SolarUpdate solar_update = {});
    // Sensor task only: bounded arithmetic and a short mutex; no network/JSON.
    void Observe(const AirSnapshot& snapshot);
    void FinishCollection(uint64_t now_ms);
    void Stop();
    bool stopped() const { return stopped_.load(); }

private:
    void Run();
    HaMinuteBuffer* buffer_ = nullptr;
    SolarUpdate solar_update_;
    std::mutex mutex_;
    std::atomic<bool> stop_{false}, collection_done_{false}, stopped_{true};
    std::atomic<uint64_t> shutdown_ms_{0};
};
}  // namespace air
