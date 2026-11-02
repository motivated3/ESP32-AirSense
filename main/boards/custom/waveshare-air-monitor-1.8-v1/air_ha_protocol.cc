#include "air_ha_protocol.h"
#include <cJSON.h>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <memory>

namespace air {
namespace {
using Json = std::unique_ptr<cJSON, decltype(&cJSON_Delete)>;
constexpr const char* kNames[] = {"co2_ppm", "hcho_ppb", "temperature_c", "humidity_pct"};
bool StringEquals(cJSON* item, const char* value) {
    return cJSON_IsString(item) && item->valuestring && std::strcmp(item->valuestring, value) == 0;
}
}  // namespace

std::optional<SolarLocation> ParseHaSolarLocation(const std::string& json) {
    if (json.size() > 4096)
        return std::nullopt;
    Json root(cJSON_ParseWithLengthOpts(json.c_str(), json.size() + 1, nullptr, true),
              cJSON_Delete);
    auto* location = cJSON_GetObjectItemCaseSensitive(root.get(), "solar_location");
    auto* latitude = cJSON_GetObjectItemCaseSensitive(location, "latitude");
    auto* longitude = cJSON_GetObjectItemCaseSensitive(location, "longitude");
    if (!cJSON_IsNumber(latitude) || !cJSON_IsNumber(longitude) ||
        !std::isfinite(latitude->valuedouble) || !std::isfinite(longitude->valuedouble) ||
        std::abs(latitude->valuedouble) > 90 || std::abs(longitude->valuedouble) > 180)
        return std::nullopt;
    return SolarLocation{static_cast<int32_t>(std::lround(latitude->valuedouble * 1e6)),
                         static_cast<int32_t>(std::lround(longitude->valuedouble * 1e6))};
}

bool HaUtcClock::Synchronize(std::string_view date, uint64_t uptime_ms) {
    if (date.size() != 29 || date.substr(25) != " GMT")
        return false;
    char weekday[4]{}, month[4]{};
    int day, year, hour, minute, second, used = 0;
    const std::string input(date);
    if (std::sscanf(input.c_str(), "%3s, %d %3s %d %d:%d:%d GMT%n", weekday, &day, month, &year,
                    &hour, &minute, &second, &used) != 7 ||
        used != 29)
        return false;
    constexpr const char* months[] = {"Jan", "Feb", "Mar", "Apr", "May", "Jun",
                                      "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"};
    unsigned m = 0;
    for (unsigned i = 0; i < 12; ++i)
        if (std::strcmp(month, months[i]) == 0)
            m = i + 1;
    using namespace std::chrono;
    const year_month_day ymd{std::chrono::year{year}, std::chrono::month{m},
                             std::chrono::day{static_cast<unsigned>(day)}};
    if (year < 2024 || year > 2099 || !ymd.ok() || hour < 0 || hour > 23 || minute < 0 ||
        minute > 59 || second < 0 || second > 59)
        return false;
    offset_ms_ = duration_cast<milliseconds>(sys_days{ymd}.time_since_epoch()).count() +
                 (hour * 3600LL + minute * 60LL + second) * 1000 - static_cast<int64_t>(uptime_ms);
    synced_ = true;
    return true;
}

std::optional<int64_t> HaUtcClock::ToEpochMs(uint64_t uptime_ms) const {
    if (!synced_)
        return std::nullopt;
    return offset_ms_ + static_cast<int64_t>(uptime_ms);
}

std::string HaIso8601(int64_t epoch_ms) {
    using namespace std::chrono;
    const sys_time<milliseconds> t{milliseconds{epoch_ms}};
    const auto day = floor<days>(t);
    const year_month_day ymd{day};
    const hh_mm_ss hms{t - day};
    char output[64];
    std::snprintf(output, sizeof(output), "%04d-%02u-%02uT%02u:%02u:%02u.%03uZ", int(ymd.year()),
                  unsigned(ymd.month()), unsigned(ymd.day()),
                  static_cast<unsigned>(hms.hours().count()) % 24,
                  static_cast<unsigned>(hms.minutes().count()) % 60,
                  static_cast<unsigned>(hms.seconds().count()) % 60,
                  static_cast<unsigned>(hms.subseconds().count()) % 1000);
    return output;
}

bool HaBatch::Capture(const HaMinuteBuffer& buffer) {
    if (!count_)
        count_ = buffer.CopyBatch(records_);
    return count_ != 0;
}

bool HaBatch::Encode(const char* device, const char* session, const HaUtcClock& clock) {
    if (!body_.empty())
        return true;
    if (!count_)
        return false;
    Json root(cJSON_CreateObject(), cJSON_Delete);
    if (!root)
        return false;
    bool ok = cJSON_AddNumberToObject(root.get(), "schema_version", 2);
    ok &= cJSON_AddStringToObject(root.get(), "device_id", device) != nullptr;
    ok &= cJSON_AddStringToObject(root.get(), "session_id", session) != nullptr;
    auto* list = cJSON_AddArrayToObject(root.get(), "records");
    if (!list)
        return false;
    for (size_t i = 0; i < count_; ++i) {
        const auto& record = records_[i];
        auto* item = cJSON_CreateObject();
        if (!item || !cJSON_AddItemToArray(list, item)) {
            cJSON_Delete(item);
            return false;
        }
        ok &= cJSON_AddNumberToObject(item, "seq", record.sequence) != nullptr;
        ok &= cJSON_AddNumberToObject(item, "uptime_ms", record.last_ms) != nullptr;
        const auto first = clock.ToEpochMs(record.first_ms), last = clock.ToEpochMs(record.last_ms);
        if (first && last) {
            ok &=
                cJSON_AddStringToObject(item, "period_start", HaIso8601(*first).c_str()) != nullptr;
            ok &= cJSON_AddStringToObject(item, "sampled_at", HaIso8601(*last).c_str()) != nullptr;
        } else {
            ok &= cJSON_AddNullToObject(item, "period_start") != nullptr;
            ok &= cJSON_AddNullToObject(item, "sampled_at") != nullptr;
        }
        ok &= cJSON_AddStringToObject(item, "clock_quality", first ? "synced" : "unsynced") !=
              nullptr;
        for (size_t j = 0; j < record.metrics.size(); ++j) {
            const auto& m = record.metrics[j];
            if (!m.count) {
                ok &= cJSON_AddNullToObject(item, kNames[j]) != nullptr;
                continue;
            }
            auto* metric = cJSON_AddObjectToObject(item, kNames[j]);
            if (!metric)
                return false;
            ok &= cJSON_AddNumberToObject(metric, "mean", m.Mean()) != nullptr;
            ok &= cJSON_AddNumberToObject(metric, "min", m.minimum) != nullptr;
            ok &= cJSON_AddNumberToObject(metric, "max", m.maximum) != nullptr;
            ok &= cJSON_AddNumberToObject(metric, "count", m.count) != nullptr;
        }
    }
    if (!ok)
        return false;
    char* encoded = cJSON_PrintUnformatted(root.get());
    if (!encoded)
        return false;
    body_ = encoded;
    cJSON_free(encoded);
    return body_.size() <= 65536;
}

bool HaBatch::CheckAck(const std::string& json, const char* device, const char* session) {
    acknowledged_ = false;
    Json ack(cJSON_ParseWithLengthOpts(json.c_str(), json.size() + 1, nullptr, true), cJSON_Delete);
    if (!ack || !count_)
        return false;
    auto* schema = cJSON_GetObjectItemCaseSensitive(ack.get(), "schema_version");
    auto* accepted = cJSON_GetObjectItemCaseSensitive(ack.get(), "accepted");
    if (!cJSON_IsNumber(schema) || schema->valuedouble != 2 ||
        !StringEquals(cJSON_GetObjectItemCaseSensitive(ack.get(), "device_id"), device) ||
        !StringEquals(cJSON_GetObjectItemCaseSensitive(ack.get(), "session_id"), session) ||
        !cJSON_IsArray(accepted) || cJSON_GetArraySize(accepted) != static_cast<int>(count_))
        return false;
    for (size_t i = 0; i < count_; ++i) {
        const auto* seq = cJSON_GetArrayItem(accepted, i);
        if (!cJSON_IsNumber(seq) || seq->valuedouble != records_[i].sequence)
            return false;
    }
    acknowledged_ = true;
    return true;
}

bool HaBatch::Commit(HaMinuteBuffer& buffer) {
    if (!acknowledged_)
        return false;
    std::array<uint32_t, kMaxRecords> sequences{};
    for (size_t i = 0; i < count_; ++i)
        sequences[i] = records_[i].sequence;
    if (!buffer.Acknowledge(std::span(sequences.data(), count_)))
        return false;
    count_ = 0;
    acknowledged_ = false;
    body_.clear();
    return true;
}
}  // namespace air
