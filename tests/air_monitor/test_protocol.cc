#include <algorithm>
#include <array>
#include "sensirion_protocol.h"
#include "test_support.h"

using namespace air;

int main() {
    const uint8_t anchor[] = {0xBE, 0xEF};
    CHECK(Crc8(anchor, 2) == 0x92);
    std::array<uint8_t, 12> sfa = {0x00, 0x64, 0xFE, 0x72, 0xB0, 0xDC,
                                   0x66, 0x66, 0x93, 0,    0,    0x81};
    Sfa40Reading hcho;
    CHECK(DecodeSfa40(sfa.data(), sfa.size(), hcho));
    NEAR(hcho.ppb, 10.0f, .001f);
    NEAR(hcho.temperature, 25.0f, .001f);
    NEAR(hcho.humidity, 50.00061f, .001f);
    CHECK(hcho.ready && hcho.within_spec);
    const uint8_t status_crc[] = {0x81, 0x75, 0x58, 0xAC};
    for (uint8_t status = 0; status < 4; ++status) {
        auto frame = sfa;
        frame[9] = status;
        frame[11] = status_crc[status];
        CHECK(DecodeSfa40(frame.data(), frame.size(), hcho));
        CHECK(hcho.ready == ((status & 1) == 0));
        CHECK(hcho.within_spec == (status == 0));
    }
    for (size_t i = 0; i < sfa.size(); ++i) {
        auto bad = sfa;
        bad[i] ^= 1;
        hcho.ppb = 123;
        CHECK(!DecodeSfa40(bad.data(), bad.size(), hcho));
        CHECK(hcho.ppb == 123);
    }
    sfa[9] = 2;
    sfa[11] = 0xE3;
    CHECK(!DecodeSfa40(sfa.data(), sfa.size(), hcho));
    CHECK(!DecodeSfa40(nullptr, 0, hcho));
    CHECK(!DecodeSfa40(sfa.data(), 11, hcho));
    CHECK(!DecodeSfa40(sfa.data(), 13, hcho));
    const uint8_t scd[] = {0x03, 0x60, 0x17, 0x66, 0x66, 0x93, 0x80, 0, 0xA2};
    Scd41Reading co2;
    CHECK(DecodeScd41(scd, sizeof(scd), co2));
    CHECK(co2.ppm == 864);
    NEAR(co2.temperature, 25.f, .001f);
    NEAR(co2.humidity, 50.000763f, .001f);
    for (size_t i = 0; i < sizeof(scd); ++i) {
        auto bad = std::array<uint8_t, 9>{};
        std::copy(scd, scd + 9, bad.begin());
        bad[i] ^= 1;
        CHECK(!DecodeScd41(bad.data(), bad.size(), co2));
    }
    CHECK(!DecodeScd41(scd, 8, co2));
    CHECK(!DecodeScd41(scd, 10, co2));
    bool ready = true;
    const uint8_t not_ready[] = {0x80, 0, 0xA2};
    const uint8_t is_ready[] = {0x80, 1, 0x93};
    CHECK(DecodeScd41Ready(not_ready, 3, ready) && !ready);
    CHECK(DecodeScd41Ready(is_ready, 3, ready) && ready);
    std::puts("protocol: CRC, scaling, atomic decode, status and lengths passed");
}
