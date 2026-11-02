#include "air_model.h"
#include "test_support.h"

using namespace air;
int main() {
    AirModel model;
    Scd41Reading co2{864, 25, 50};
    Sfa40Reading stable{10, 25, 50, true, true, 0};
    Sfa40Reading provisional{12, 25, 50, true, false, 2};
    Sfa40Reading warming{0, 25, 50, false, false, 3};
    CHECK(!model.Snapshot(60000).co2.has_value);
    model.ApplyScd41(co2, 0);
    CHECK(model.Snapshot(0).co2.has_value);
    CHECK(!model.Snapshot(15000).co2.stale);
    CHECK(model.Snapshot(15001).co2.stale);
    model.ApplyScd41(co2, 20000);
    CHECK(!model.Snapshot(20000).co2.stale);
    model.ApplySfa40(warming, 60000);
    auto snap = model.Snapshot(100000);
    CHECK(!snap.hcho.has_value && !snap.hcho.stale && snap.hcho.connected);
    model.ApplySfa40(provisional, 600000);
    CHECK(model.Snapshot(600000).hcho.has_value);
    CHECK(!model.Snapshot(600000).hcho.within_spec);
    CHECK(!model.History(Metric::Hcho)[120 % kHistorySize].valid);
    CHECK(!model.Snapshot(605000).hcho.stale);
    CHECK(model.Snapshot(605001).hcho.stale);
    model.ApplySfa40(stable, 610000);
    CHECK(model.History(Metric::Hcho)[122 % kHistorySize].valid);
    model.Failure(SensorId::Sfa40, SensorError::Crc);
    CHECK(model.Snapshot(610100).hcho.last_value_ms == 610000);
    model.ApplySfa40(warming, 611000);
    CHECK(!model.Snapshot(611000).hcho.has_value);
    for (int i = 0; i < 3; ++i)
        model.Failure(SensorId::Scd41, SensorError::Transport);
    CHECK(!model.Snapshot(611000).co2.connected);
    CHECK(model.Snapshot(611000).hcho.connected);
    model.Acknowledge(SensorId::Scd41);
    CHECK(model.Snapshot(611000).co2.connected);
    CHECK(model.Snapshot(611000).co2.stale);
    AirModel gaps;
    gaps.ApplyScd41(co2, 0);
    gaps.ApplyScd41({1000, 25, 50}, 10000);
    const auto& history = gaps.History(Metric::Co2);
    CHECK(history[0].valid && !history[1].valid && history[2].valid);
    gaps.ApplyScd41({1200, 25, 50}, 14999);
    CHECK(history[2].value == 1200);
    gaps.ApplyScd41(co2, 1800000);
    CHECK(history[0].bucket == 360 && history[0].value == 864);
    const uint64_t late = (uint64_t{1} << 32) + 1000;
    gaps.ApplySfa40(stable, late);
    CHECK(!gaps.Snapshot(late + 5000).hcho.stale);
    CHECK(gaps.Snapshot(late + 5001).hcho.stale);
    model.SetAscEnabled(false);
    CHECK(model.Snapshot(0).asc_enabled == 0);
    std::puts("model: validity, warmup, independent failures, age and history passed");
}
