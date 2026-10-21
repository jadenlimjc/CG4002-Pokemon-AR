import base64
import hashlib
import json
import random
import secrets
import struct
import time
import zlib
from pathlib import Path

from process_telemetry import BODY, CRC, decode_packet
from main import Action

# Little-endian wire format shared with esp32/main/demo_protocol.h.
MAGIC = b"DEMO"
HEADER = struct.Struct("<4sBIIIH")
FRAME_CRC = struct.Struct("<I")
CHUNK = 512
MAX_FILE = 65536
FILE_CHUNK, FILE_ECHO, FILE_FINISH, FILE_RECEIPT, PIPELINE, PIPELINE_REPLY, TRANSFER_ERROR = range(1, 8)


def encode_frame(kind, transfer, offset, total, data=b""):
    body = HEADER.pack(MAGIC, kind, transfer, offset, total, len(data)) + data
    return body + FRAME_CRC.pack(zlib.crc32(body))


def decode_frame(payload):
    if len(payload) < HEADER.size + FRAME_CRC.size:
        raise ValueError("short demo frame")
    magic, kind, transfer, offset, total, length = HEADER.unpack_from(payload)
    if (magic != MAGIC or length > CHUNK or len(payload) != HEADER.size + length + FRAME_CRC.size
            or FRAME_CRC.unpack_from(payload, len(payload) - FRAME_CRC.size)[0] != zlib.crc32(payload[:-FRAME_CRC.size])):
        raise ValueError("invalid demo frame / CRC")
    return kind, transfer, offset, total, payload[HEADER.size:-FRAME_CRC.size]


MODES = ("auto", "file", "pipeline")
# SI IMU samples (m/s^2, rad/s), touch mask, flags; restart after editing.
DUMMY_SAMPLES = (
    (1.2, -0.8, 9.8, 0.2, -0.3, 0.45, 0, 0),
    (-4.5, 2.2, 9.0, -0.8, 0.7, 0.3, 5, 1),
    (8.0, -1.2, 8.5, 1.6, -0.9, 0.25, 0, 0),
)


class TransferController:
    def __init__(self, client, model_id, file_path, output_dir, record=None):
        self.client, self.model_id = client, model_id
        self.base = f"esp32/{model_id}"
        self.file_path, self.output_dir = Path(file_path), Path(output_dir)
        self.record = record or (lambda *args: None)
        self.mode = None
        self.target_mode = "auto"
        self.mode_wait = None
        self.pending = None
        self.message = "Waiting for firmware mode confirmation"
        self.last_result = None
        self.sequence = 0

    def note(self, message):
        self.message = message
        self.record("demo", message)

    def disconnected(self):
        self.pending = None
        self.mode = None
        self.mode_wait = None
        self.note("Disconnected; operation cancelled, awaiting mode confirmation")

    def cycle_mode(self):
        if self.pending or self.mode_wait or self.mode is None:
            self.note("Wait for the current operation / mode confirmation")
            return
        self.target_mode = MODES[(MODES.index(self.mode) + 1) % len(MODES)]
        self.request_mode()

    def request_mode(self):
        self.mode_wait = [time.monotonic(), 1]
        self.client.publish(self.base + "/config", "mode:" + self.target_mode)
        self.note(f"Requesting {self.target_mode.upper()}")

    def tick(self, online):
        now = time.monotonic()
        if not online:
            return
        if self.mode is None and self.mode_wait is None:
            self.request_mode()
        if self.mode_wait and now - self.mode_wait[0] >= 2:
            if self.mode_wait[1] >= 4:
                self.mode_wait = None
                self.mode = None
                # Keep unknown until a fresh acknowledgement; no false success.
                self.note("Mode ACK timeout; check firmware/connection")
                return
            self.mode_wait[0] = now
            self.mode_wait[1] += 1
            self.client.publish(self.base + "/config", "mode:" + self.target_mode)
        if self.pending and now - self.pending["sent"] >= 2:
            if self.pending["attempts"] >= 4:
                self.pending = None
                self.note("FAILED: reply timeout; press Send to start a fresh operation")
                return
            self.pending["attempts"] += 1
            self.pending["sent"] = now
            self.client.publish(self.base + "/demo_in", self.pending["frame"])

    def _send(self, frame):
        self.pending.update(frame=frame, sent=time.monotonic(), attempts=1)
        self.client.publish(self.base + "/demo_in", frame)

    def trigger(self):
        if self.pending or self.mode_wait or self.mode is None:
            self.note("Wait for the current operation / mode confirmation")
            return
        if self.mode == "auto":
            self.note("AUTO streams continuously; Config selects FILE or PIPELINE")
            return
        transfer = secrets.randbelow(0xffffffff) + 1
        self.last_result = None
        if self.mode == "file":
            try:
                with self.file_path.open("rb") as source:
                    data = source.read(MAX_FILE + 1)
                if not 0 < len(data) <= MAX_FILE:
                    raise ValueError(f"file must be 1..{MAX_FILE} bytes")
            except (OSError, ValueError) as error:
                self.note(f"File not sent: {error}")
                return
            self.pending = dict(id=transfer, started=time.monotonic(), data=data,
                                returned=bytearray(), offset=0, phase="chunks")
            self.note(f"FILE {transfer:08x}: sending {self.file_path.name}, {len(data)} bytes")
            self._send(encode_frame(FILE_CHUNK, transfer, 0, len(data), data[:CHUNK]))
        else:
            self.sequence = (self.sequence + 1) & 0xffffffff
            body = BODY.pack(self.sequence, 0, *random.choice(DUMMY_SAMPLES))
            packet = body + CRC.pack(zlib.crc32(body))
            self.pending = dict(id=transfer, started=time.monotonic(), packet=packet)
            self.note(f"U96 -> FB | {transfer:08x} | ax={decode_packet(packet).features[0]}")
            self._send(encode_frame(PIPELINE, transfer, 0, 1, packet))

    def on_message(self, suffix, payload, retained=False):
        if retained:
            return
        if suffix == "mode":
            mode = payload.decode("ascii", errors="replace")
            if mode in MODES:
                # A fresh mode ACK can also signal a firmware reconnect, which
                # clears its RAM transfer state. Never resume an old operation.
                self.pending = None
                self.mode, self.target_mode, self.mode_wait = mode, mode, None
                self.note(f"{mode.upper()} confirmed by FireBeetle")
            return
        if suffix != "demo_out" or not self.pending:
            return
        try:
            kind, transfer, offset, total, data = decode_frame(payload)
            p = self.pending
            if transfer != p["id"]:
                return
            if kind == TRANSFER_ERROR:
                if data == b"\x01":
                    raise ValueError("FireBeetle has insufficient free memory for this file; choose a smaller file")
                raise ValueError("FireBeetle rejected the transfer")
            if self.mode == "pipeline":
                if kind != PIPELINE_REPLY or offset != 0 or total != 1:
                    return
                before = decode_packet(p["packet"], require_crc=True)
                after = decode_packet(data, require_crc=True)
                expected = list(before.features)
                # Match the ESP32 float32 subtraction, including its rounding.
                expected[0] = struct.unpack("<f", struct.pack("<f", -1.0 - expected[0]))[0]
                expected[-1] ^= 2
                if after.sequence != before.sequence or after.features != tuple(expected):
                    raise ValueError("FireBeetle modification mismatch")
                result = dict(model_id=self.model_id, demo=True, transfer_id=f"{transfer:08x}",
                              action=random.choice(list(Action)).value, confidence=1.0,
                              sample_sequence=after.sequence, sample_timestamp_ms=after.timestamp_ms,
                              timestamp_ms=int(time.time()*1000), before_ax=before.features[0],
                              after_ax=after.features[0], round_trip_ms=round((time.monotonic()-p["started"])*1000, 2))
                info = self.client.publish(f"ultra96/{self.model_id}/inference", json.dumps(result))
                if info.rc != 0:
                    raise ValueError(f"visualiser event publish failed ({info.rc})")
                self.record("pipeline_result", json.dumps(result))
                self.last_result = result
                self.pending = None
                self.note(f"FB -> U96 verified: ax {before.features[0]} -> {after.features[0]} | {result['action']} -> visualiser (await display)")
            elif self.mode == "file":
                source = p["data"]
                if total != len(source):
                    raise ValueError("file size mismatch")
                if kind == FILE_ECHO and p["phase"] == "chunks":
                    if offset != p["offset"]:
                        return  # delayed duplicate reply
                    expected = source[offset:offset+CHUNK]
                    if data != expected:
                        raise ValueError("file readback differs from source")
                    p["returned"].extend(data)
                    p["offset"] += len(data)
                    offset = p["offset"]
                    if offset == len(source):
                        p["phase"] = "finish"
                        self._send(encode_frame(FILE_FINISH, transfer, offset, len(source)))
                    else:
                        self._send(encode_frame(FILE_CHUNK, transfer, offset, len(source), source[offset:offset+CHUNK]))
                    self.message = f"FILE {transfer:08x}: read back {offset}/{len(source)} bytes"
                elif kind == FILE_RECEIPT and p["phase"] == "finish":
                    if offset != len(source) or data != struct.pack("<I", zlib.crc32(source)):
                        raise ValueError("FireBeetle complete-file CRC mismatch")
                    returned = bytes(p["returned"])
                    digest = hashlib.sha256(returned).hexdigest()
                    if returned != source:
                        raise ValueError("complete file differs")
                    elapsed = time.monotonic() - p["started"]
                    self.output_dir.mkdir(parents=True, exist_ok=True)
                    path = self.output_dir / f"{self.model_id}-{transfer:08x}-{self.file_path.name}"
                    path.write_bytes(returned)
                    result = dict(model_id=self.model_id, transfer_id=f"{transfer:08x}", name=self.file_path.name,
                                  bytes=len(source), sha256=digest, source_sha256=hashlib.sha256(source).hexdigest(),
                                  board_crc32=f"{zlib.crc32(source):08x}", seconds=round(elapsed, 3),
                                  kbps=round(len(source)*8/max(elapsed, 1e-9)/1000, 3), saved_as=str(path))
                    self.last_result = result
                    self.pending = None
                    self.note(f"FILE PASS {len(source)} bytes | {result['kbps']:.2f} kbps | SHA256 {digest}")
                    self.record("file_result", json.dumps(result))
                    self.forward_verified_file(returned, transfer)
        except (ValueError, OSError) as error:
            self.pending = None
            self.note(f"FAILED: {error}")

    def forward_verified_file(self, data, transfer):
        """Forward the verified FireBeetle readback to the Android text display.

        This sends complete file bytes as UTF-8 or lossless base64 plus a hash.
        The current phone app has no ACK/hash verifier; never claim phone PASS.
        """
        try:
            try:
                content, encoding = data.decode("utf-8"), "utf-8"
            except UnicodeDecodeError:
                content, encoding = base64.b64encode(data).decode("ascii"), "base64"
            result = dict(model_id=self.model_id, type="demo_file", name=self.file_path.name,
                          transfer_id=f"{transfer:08x}",
                          bytes=len(data), sha256=hashlib.sha256(data).hexdigest(),
                          firebeetle_verified=True, encoding=encoding, content=content)
            payload = json.dumps(result, ensure_ascii=True)
            if not data or len(payload.encode("utf-8")) > 4096:
                raise ValueError("file envelope exceeds phone's 4096-byte limit or file is empty; use a smaller file")
            info = self.client.publish(f"ultra96/{self.model_id}/inference", payload)
            if info.rc != 0:
                raise ValueError(f"MQTT publish failed ({info.rc})")
            self.record("visualiser_file_sent", json.dumps(result))
            self.message = "FB FILE PASS | File sent to visualiser; compare content/hash on phone (no ACK)"
        except (OSError, ValueError) as error:
            self.note(f"FB FILE PASS | Visualiser file not sent: {error}")
