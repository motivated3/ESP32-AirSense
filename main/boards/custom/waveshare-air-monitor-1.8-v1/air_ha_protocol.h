#pragma once
#include <string>
#include <string_view>
#include "air_ha_model.h"
#include "air_solar_theme.h"

namespace air {
class HaUtcClock {
public:
    bool Synchronize(std::string_view http_date, uint64_t uptime_ms);
    std::optional<int64_t> ToEpochMs(uint64_t uptime_ms) const;
    bool synced() const { return synced_; }

private:
    int64_t offset_ms_ = 0;
    bool synced_ = false;
};
std::string HaIso8601(int64_t epoch_ms);
std::optional<SolarLocation> ParseHaSolarLocation(const std::string& json);

// Captured records and encoded bytes stay unchanged until a matching ACK.
class HaBatch {
public:
    static constexpr size_t kMaxRecords = 16;
    bool Capture(const HaMinuteBuffer& buffer);
    bool Encode(const char* device, const char* session, const HaUtcClock& clock);
    bool CheckAck(const std::string& json, const char* device, const char* session);
    bool Commit(HaMinuteBuffer& buffer);
    const std::string& body() const { return body_; }

private:
    std::array<HaMinute, kMaxRecords> records_{};
    size_t count_ = 0;
    bool acknowledged_ = false;
    std::string body_;
};
}  // namespace air
