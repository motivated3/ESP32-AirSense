#include "air_ha_model.h"
#include <algorithm>
#include <cmath>

namespace air {
bool HaMetric::Add(float value, float lower, float upper) {
    if (!std::isfinite(value) || value < lower || value > upper)
        return false;
    if (!count)
        minimum = maximum = value;
    minimum = std::min(minimum, value);
    maximum = std::max(maximum, value);
    sum += value;
    ++count;
    return true;
}

void HaMinuteBuffer::Sample(size_t metric, float value, float lower, float upper, uint64_t at) {
    if (!active_.metrics[metric].Add(value, lower, upper))
        return;
    if (!has_sample_)
        active_.first_ms = active_.last_ms = at;
    active_.first_ms = std::min(active_.first_ms, at);
    active_.last_ms = std::max(active_.last_ms, at);
    has_sample_ = true;
}

void HaMinuteBuffer::Observe(const AirSnapshot& s) {
    const uint64_t bucket = s.now_ms / 60000;
    const auto fresh = [this, &s](const ChannelState& channel, size_t index) {
        if (!channel.has_value || !channel.connected || !channel.ready || channel.stale ||
            channel.last_value_ms > s.now_ms ||
            (seen_[index] && channel.last_value_ms <= seen_ms_[index]))
            return false;
        seen_[index] = true;
        seen_ms_[index] = channel.last_value_ms;
        return true;
    };
    const bool scd_fresh = fresh(s.co2, 0), sfa_fresh = fresh(s.hcho, 1);
    const auto sample_bucket = [&]() {
        if (scd_fresh && s.co2.last_value_ms / 60000 == bucket_) {
            if (s.co2.within_spec && s.co2.environment_ok)
                Sample(0, s.scd.ppm, 400, 5000, s.co2.last_value_ms);
            if (s.co2.environment_ok) {
                Sample(2, s.scd.temperature, -10, 60, s.co2.last_value_ms);
                Sample(3, s.scd.humidity, 0, 95, s.co2.last_value_ms);
            }
        }
        if (sfa_fresh && s.hcho.last_value_ms / 60000 == bucket_ && s.hcho.within_spec &&
            s.hcho.environment_ok)
            Sample(1, s.sfa.ppb, 0, 1000, s.hcho.last_value_ms);
    };
    if (active_started_ && bucket != bucket_) {
        // A sensor transaction can finish just after the minute boundary even
        // though its acquisition timestamp belongs to the minute being closed.
        sample_bucket();
        Close((bucket_ + 1) * 60000 - 1);
    }
    if (!active_started_) {
        active_started_ = true;
        bucket_ = bucket;
    }
    sample_bucket();
}

void HaMinuteBuffer::Close(uint64_t end_ms) {
    if (!has_sample_) {
        active_.first_ms = bucket_ * 60000;
        active_.last_ms = std::max(active_.first_ms, end_ms);
    }
    active_.sequence = next_sequence_++;
    if (size_ == kCapacity) {
        ++dropped_;
    } else {
        records_[(head_ + size_) % kCapacity] = active_;
        ++size_;
    }
    active_ = {};
    active_started_ = has_sample_ = false;
}

void HaMinuteBuffer::Flush(uint64_t now_ms) {
    if (active_started_ && has_sample_)
        Close(std::min(now_ms, (bucket_ + 1) * 60000 - 1));
}

size_t HaMinuteBuffer::CopyBatch(std::span<HaMinute> output) const {
    const size_t count = std::min(output.size(), size_);
    for (size_t i = 0; i < count; ++i)
        output[i] = records_[(head_ + i) % kCapacity];
    return count;
}

bool HaMinuteBuffer::Acknowledge(std::span<const uint32_t> sequences) {
    if (sequences.empty() || sequences.size() > size_)
        return false;
    for (size_t i = 0; i < sequences.size(); ++i)
        if (records_[(head_ + i) % kCapacity].sequence != sequences[i])
            return false;
    head_ = (head_ + sequences.size()) % kCapacity;
    size_ -= sequences.size();
    return true;
}

void HaRetry::Failure(uint64_t now, uint32_t jitter_ms) {
    const uint64_t delay = std::min<uint64_t>(300000, 5000ULL << std::min(failures_, 6U));
    failures_ = std::min(failures_ + 1, 6U);
    next_ms_ = now + delay + std::min<uint32_t>(jitter_ms, 1000);
}
}  // namespace air
