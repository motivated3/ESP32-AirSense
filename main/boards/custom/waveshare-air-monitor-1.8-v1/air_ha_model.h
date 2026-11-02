#pragma once
#include <array>
#include <optional>
#include <span>
#include "air_types.h"

namespace air {
struct HaMetric {
    double sum = 0;
    float minimum = 0, maximum = 0;
    uint32_t count = 0;
    bool Add(float value, float lower, float upper);
    double Mean() const { return count ? sum / count : 0; }
};
struct HaMinute {
    std::array<HaMetric, 4> metrics{};
    uint64_t first_ms = 0, last_ms = 0;
    uint32_t sequence = 0;
};

// Owned by the uploader; callers serialize access with its short-lived mutex.
// Full queues retain their oldest records (including any in-flight batch).
class HaMinuteBuffer {
public:
    static constexpr size_t kCapacity = 512;
    void Observe(const AirSnapshot& snapshot);
    void Flush(uint64_t now_ms);
    size_t CopyBatch(std::span<HaMinute> output) const;
    bool Acknowledge(std::span<const uint32_t> sequences);
    size_t size() const { return size_; }
    uint32_t dropped() const { return dropped_; }

private:
    void Close(uint64_t end_ms);
    void Sample(size_t metric, float value, float lower, float upper, uint64_t at);
    std::array<HaMinute, kCapacity> records_{};
    HaMinute active_{};
    size_t head_ = 0, size_ = 0;
    uint64_t bucket_ = 0;
    uint64_t seen_ms_[2]{};
    bool seen_[2]{}, active_started_ = false, has_sample_ = false;
    uint32_t next_sequence_ = 1, dropped_ = 0;
};

class HaRetry {
public:
    bool Due(uint64_t now) const { return now >= next_ms_; }
    void Failure(uint64_t now, uint32_t jitter_ms);
    void Success(uint64_t now) {
        failures_ = 0;
        next_ms_ = now + 2000;
    }
    void Reconnected(uint64_t now) {
        failures_ = 0;
        next_ms_ = now;
    }

private:
    uint64_t next_ms_ = 0;
    unsigned failures_ = 0;
};
}  // namespace air
