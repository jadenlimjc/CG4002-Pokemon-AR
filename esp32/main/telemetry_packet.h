#pragma once

#include <stddef.h>
#include <stdint.h>

// Little-endian ESP32 wire format. The final CRC covers the preceding 23 bytes.
struct __attribute__((packed)) TelemetryPacket {
    uint32_t sample_index;
    uint32_t timestamp_ms;
    int16_t accel_x;
    int16_t accel_y;
    int16_t accel_z;
    int16_t gyro_x;
    int16_t gyro_y;
    int16_t gyro_z;
    uint16_t hall_raw;
    uint8_t flags;
    uint32_t crc32;
};

static_assert(sizeof(TelemetryPacket) == 27, "Unexpected telemetry packet layout");
static_assert(offsetof(TelemetryPacket, crc32) == 23, "Unexpected CRC offset");

// CRC-32/ISO-HDLC, matching Python zlib.crc32. Detects accidental corruption;
// it does not authenticate the sender or replace encryption.
inline uint32_t telemetryCrc32(const uint8_t* bytes, size_t length) {
    uint32_t crc = 0xffffffffu;
    for (size_t i = 0; i < length; ++i) {
        crc ^= bytes[i];
        for (uint8_t bit = 0; bit < 8; ++bit) {
            crc = (crc >> 1) ^ ((crc & 1u) ? 0xedb88320u : 0u);
        }
    }
    return crc ^ 0xffffffffu;
}
