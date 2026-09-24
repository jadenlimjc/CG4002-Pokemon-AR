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

// Bit 7 asks U96 to acknowledge this one telemetry packet. Bit 0 retains its
// hall-trigger meaning, so the existing phone and inference format is unchanged.
constexpr uint8_t TELEMETRY_RTT_REQUEST = 0x80;

struct __attribute__((packed)) TelemetryAck {
    uint32_t sample_index;
    uint32_t timestamp_ms;
    uint32_t packet_crc32; // match the exact packet, including after a reboot
};
static_assert(sizeof(TelemetryAck) == 12, "Unexpected telemetry ACK layout");

// Cumulative snapshot for this MQTT connection. A later snapshot recovers
// aggregate statistics if an earlier one is lost.
struct __attribute__((packed)) RttReport {
    char magic[4]; // RTT1
    uint32_t session;
    uint32_t report_index;
    uint32_t samples;
    uint64_t total_us;
    uint32_t minimum_us, maximum_us;
    uint32_t timeouts, cancelled, publish_failures, late_acks;
    uint32_t pending;
    uint32_t crc32;
};
static_assert(sizeof(RttReport) == 56, "Unexpected RTT report layout");
