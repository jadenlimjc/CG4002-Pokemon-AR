#pragma once
#include <string.h>
#include <memory>
#include <new>
#include "telemetry_packet.h"

// Little endian, bounded frames. NetworkTask exclusively owns this receiver.
namespace demo {
constexpr size_t CHUNK = 512;
constexpr uint32_t MAX_FILE = 65536;
enum Kind : uint8_t { FILE_CHUNK=1, FILE_ECHO, FILE_FINISH, FILE_RECEIPT, PIPELINE, PIPELINE_REPLY, TRANSFER_ERROR };
struct __attribute__((packed)) Header {
    char magic[4];
    uint8_t kind;
    uint32_t id, offset, total;
    uint16_t length;
};
static_assert(sizeof(Header) == 19, "Demo header layout mismatch");

class Receiver {
    // Reserve only the actual incoming size, after Wi-Fi/SSH have started.
    // Keeping MAX_FILE bytes in this global object's .bss exhausts static DRAM.
    std::unique_ptr<uint8_t[]> file;
    uint32_t id = 0, total = 0, received = 0, completedCrc = 0;
    bool complete = false;

    static size_t finishReply(const Header& h, uint8_t* output) {
        memcpy(output, &h, sizeof(h));
        uint32_t crc = telemetryCrc32(output, sizeof(h) + h.length);
        memcpy(output + sizeof(h) + h.length, &crc, 4);
        return sizeof(h) + h.length + 4;
    }
public:
    void reset() {
        file.reset();
        id = total = received = completedCrc = 0;
        complete = false;
    }
    // Returns the reply size, or zero for an invalid/wrong-mode request.
    size_t handle(const uint8_t* input, size_t size, bool fileMode, bool pipelineMode,
                  uint8_t* output, uint32_t now) {
        if (size < sizeof(Header) + 4) return 0;
        Header h;
        memcpy(&h, input, sizeof(h));
        uint32_t crc;
        memcpy(&crc, input + size - 4, 4);
        if (memcmp(h.magic, "DEMO", 4) || h.length > CHUNK ||
            size != sizeof(h) + h.length + 4 ||
            crc != telemetryCrc32(input, size - 4)) return 0;
        const uint8_t* data = input + sizeof(h);
        uint8_t* reply = output + sizeof(h);
        if (fileMode && h.kind == FILE_CHUNK) {
            if (!h.id || !h.total || h.total > MAX_FILE || !h.length ||
                h.offset > h.total || h.length > h.total - h.offset) return 0;
            if (h.id != id) {
                if (h.offset != 0) return 0;
                reset(); // Release the previous transfer before allocating.
                file.reset(new (std::nothrow) uint8_t[h.total]);
                if (!file) {
                    h.kind = TRANSFER_ERROR;
                    h.length = 1;
                    reply[0] = 1; // Insufficient contiguous heap for this file.
                    return finishReply(h, output);
                }
                id = h.id; total = h.total;
            }
            if (h.total != total || complete || !file) return 0;
            if (h.offset == received) {
                memcpy(file.get() + received, data, h.length);
                received += h.length;
            } else if (h.offset > received || h.length > received - h.offset ||
                       memcmp(file.get() + h.offset, data, h.length)) return 0;
            // Echo bytes read from the stored file, including on a retry.
            memcpy(reply, file.get() + h.offset, h.length);
            h.kind = FILE_ECHO;
        } else if (fileMode && h.kind == FILE_FINISH) {
            if (!id || h.id != id || h.total != total || h.offset != total ||
                received != total || h.length != 0) return 0;
            if (!complete) {
                completedCrc = telemetryCrc32(file.get(), total);
                complete = true;
                file.reset(); // Keep only the receipt for lost-reply retries.
            }
            memcpy(reply, &completedCrc, 4);
            h.kind = FILE_RECEIPT; h.length = 4;
        } else if (pipelineMode && h.kind == PIPELINE) {
            if (!h.id || h.length != sizeof(TelemetryPacket) || h.offset || h.total != 1) return 0;
            TelemetryPacket p;
            memcpy(&p, data, sizeof(p));
            if (p.crc32 != telemetryCrc32(data, offsetof(TelemetryPacket, crc32))) return 0;
            // Visible, deterministic modification for the manual float32 demo.
            p.accel_x = -1.0f - p.accel_x;
            p.flags ^= 0x02;
            p.timestamp_ms = now;
            p.crc32 = telemetryCrc32(reinterpret_cast<const uint8_t*>(&p), offsetof(TelemetryPacket, crc32));
            memcpy(reply, &p, sizeof(p));
            h.kind = PIPELINE_REPLY;
        } else return 0;
        return finishReply(h, output);
    }
};
}
