#pragma once
#include "air_types.h"
namespace air {
uint8_t Crc8(const uint8_t* bytes, size_t length);
bool DecodeScd41(const uint8_t* bytes, size_t length, Scd41Reading& result);
bool DecodeSfa40(const uint8_t* bytes, size_t length, Sfa40Reading& result);
bool DecodeScd41Ready(const uint8_t* bytes, size_t length, bool& result);
bool DecodeWord(const uint8_t* bytes, size_t length, uint16_t& result);
}  // namespace air
