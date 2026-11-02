#include "sensirion_protocol.h"
#include <algorithm>
namespace air {
uint8_t Crc8(const uint8_t* bytes, size_t length) {
    uint8_t crc = 0xFF;
    for (size_t i = 0; i < length; ++i) {
        crc ^= bytes[i];
        for (int bit = 0; bit < 8; ++bit) {
            crc = (crc & 0x80) ? static_cast<uint8_t>((crc << 1) ^ 0x31)
                               : static_cast<uint8_t>(crc << 1);
        }
    }
    return crc;
}
bool DecodeWord(const uint8_t* bytes, size_t length, uint16_t& result) {
    if (!bytes || length != 3 || Crc8(bytes, 2) != bytes[2])
        return false;
    result = (static_cast<uint16_t>(bytes[0]) << 8) | bytes[1];
    return true;
}
bool DecodeScd41(const uint8_t* bytes, size_t length, Scd41Reading& result) {
    if (!bytes || length != 9)
        return false;
    uint16_t co2, t, rh;
    if (!DecodeWord(bytes, 3, co2) || !DecodeWord(bytes + 3, 3, t) || !DecodeWord(bytes + 6, 3, rh))
        return false;
    result = {co2, -45.f + 175.f * t / 65535.f, 100.f * rh / 65535.f};
    return true;
}
bool DecodeSfa40(const uint8_t* bytes, size_t length, Sfa40Reading& result) {
    if (!bytes || length != 12)
        return false;
    uint16_t hcho, rh, t, status_word;
    if (!DecodeWord(bytes, 3, hcho) || !DecodeWord(bytes + 3, 3, rh) ||
        !DecodeWord(bytes + 6, 3, t) || !DecodeWord(bytes + 9, 3, status_word))
        return false;
    // Status is the first byte of the final CRC group, not the low word byte.
    const uint8_t status = bytes[9];
    result = {hcho * .1f,
              -45.f + 175.f * t / 65535.f,
              std::clamp(125.f * rh / 65535.f - 6.f, 0.f, 100.f),
              (status & 1) == 0,
              (status & 3) == 0,
              status};
    return true;
}
bool DecodeScd41Ready(const uint8_t* bytes, size_t length, bool& result) {
    uint16_t word;
    if (!DecodeWord(bytes, length, word))
        return false;
    result = (word & 0x7FF) != 0;
    return true;
}
}  // namespace air
