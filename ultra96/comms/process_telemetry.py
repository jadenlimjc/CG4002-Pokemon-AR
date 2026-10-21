from collections import deque
from dataclasses import dataclass
from queue import Full, Queue
from pathlib import Path
import struct
import sys
import time
import zlib

import numpy as np

# Reuse the training implementation, including when main.py is run directly.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from real_data.preprocess_real_gestures import (
    ACCEL_RANGE_G, GRAVITY_M_S2, GYRO_RANGE_DPS, normalize_samples,
)

# The packet adapter reverses main_oop MotionSensor's Adafruit SI conversion.
# Match Adafruit's sensitivity, especially 65.5 rather than 32768 / 500.
SIGNED_SENSOR_COUNTS = 1 << 15
ACCEL_SCALE = 1.0 / 4096.0
GYRO_SCALE = 1.0 / 65.5


def model_input(features):
    """Convert the live [256, 8] buffer to the CNN's normalized [6, 256] input.

    The buffer holds g and degrees/s; training uses fractions of sensor range.
    Touch fields are excluded. Keep the shared window immutable.
    """
    features = np.asarray(features)
    if features.shape != (256, 8):
        raise ValueError(f"Expected live window (256, 8), got {features.shape}")
    physical = np.array(features[:, :6], dtype=np.float32, copy=True)
    physical[:, :3] *= GRAVITY_M_S2
    physical[:, 3:] = np.deg2rad(physical[:, 3:])
    return np.ascontiguousarray(normalize_samples(physical).T)


# ESP32 wire format: sequence, milliseconds, IMU, touch mask, flags, optional CRC.
BODY = struct.Struct("<IIhhhhhhHB")
CRC = struct.Struct("<I")
CHANGE_GATED = 0x02
STREAM_START = 0x04
SAMPLE_PERIOD_MS = 10


class PacketError(ValueError):
    def __init__(self, kind):
        self.kind = kind
        super().__init__(kind)


@dataclass(frozen=True)
class Packet:
    sequence: int
    timestamp_ms: int
    features: tuple
    checked: bool


@dataclass(frozen=True)
class InferenceWindow:
    features: np.ndarray
    last_sequence: int
    timestamp_ms: int | None
    received_at: float | None = None
    queued_at: float | None = None


def decode_packet(payload, require_crc=False):
    if len(payload) not in (BODY.size, BODY.size + CRC.size):
        raise PacketError("bad_length")
    checked = len(payload) == BODY.size + CRC.size
    if require_crc and not checked:
        raise PacketError("missing_crc")
    if checked and CRC.unpack_from(payload, BODY.size)[0] != zlib.crc32(payload[:BODY.size]):
        raise PacketError("bad_crc")
    sequence, timestamp, *features = BODY.unpack_from(payload)
    return Packet(sequence, timestamp, tuple(features), checked)


class SequenceStats:
    """Observed gaps, not an estimate of corruption or proven network loss.

    Without a boot ID, backwards counters cannot conclusively distinguish a
    restart from reordering. Record that ambiguity and begin a new baseline.
    """
    def __init__(self):
        self.last_sequence = None
        self.last_timestamp = None
        self.gap_slots = 0
        self.duplicates = 0
        self.backwards = 0

    def observe(self, packet):
        if self.last_sequence is not None:
            delta = (packet.sequence - self.last_sequence) & 0xffffffff
            if delta == 0 and packet.timestamp_ms == self.last_timestamp:
                self.duplicates += 1
                return False
            if 0 < delta < 0x80000000:
                self.gap_slots += delta - 1
            else:
                self.backwards += 1
        self.last_sequence = packet.sequence
        self.last_timestamp = packet.timestamp_ms
        return True


class TelemetryBuffer:
    def __init__(self, window_size=256, hop_size=25, max_gap_fill=5, queue_maxsize=10):
        self.window_size = window_size
        self.hop_size = hop_size
        self.step_counter = 0
        self.max_gap_fill = max_gap_fill
        self.output_queue = Queue(maxsize=queue_maxsize)
        self.buffer = deque(maxlen=window_size)
        self.expected_seq = None
        self.sequence_stats = SequenceStats()
        self.last_gated_timestamp = None

    def _convert_units(self, raw_readings: tuple) -> list:
        ax, ay, az, gx, gy, gz, touch_mask, flags = raw_readings
        any_touch = flags & 0x01

        return [
            ax * ACCEL_SCALE,
            ay * ACCEL_SCALE,
            az * ACCEL_SCALE,
            gx * GYRO_SCALE,
            gy * GYRO_SCALE,
            gz * GYRO_SCALE,
            float(touch_mask),
            float(any_touch),
        ]

    def add_packet(self, payload: bytes, received_at=None):
        self.received_at = time.monotonic() if received_at is None else received_at
        try:
            packet = decode_packet(payload)
        except PacketError:
            return
        if not self.sequence_stats.observe(packet):
            return
        sample_index = packet.sequence
        raw_features = packet.features

        converted = self._convert_units(raw_features)

        if raw_features[-1] & CHANGE_GATED:
            self._add_change_gated(packet, converted)
            return
        if self.last_gated_timestamp is not None:
            self.buffer.clear()
            self.step_counter = 0
            self.expected_seq = None
            self.last_gated_timestamp = None

        if self.expected_seq is None:
            self.expected_seq = sample_index

        gap = (sample_index - self.expected_seq) & 0xffffffff

        if gap == 0:
            self._push_and_emit(converted, sample_index, packet.timestamp_ms)
            self.expected_seq = (sample_index + 1) & 0xffffffff

        elif 0 < gap <= self.max_gap_fill:
            # Pad missing sequence slots with last known frame
            last_frame = self.buffer[-1] if len(self.buffer) > 0 else converted
            for index in range(gap):
                sequence = (self.expected_seq + index) & 0xffffffff
                self._push_and_emit(last_frame, sequence, None)
            self._push_and_emit(converted, sample_index, packet.timestamp_ms)
            self.expected_seq = (sample_index + 1) & 0xffffffff

        else:
            # Large sequence jump: Reset window
            self.buffer.clear()
            self.step_counter = 0
            self._push_and_emit(converted, sample_index, packet.timestamp_ms)
            self.expected_seq = (sample_index + 1) & 0xffffffff

    def _add_change_gated(self, packet, converted):
        """Restore 10 ms slots using the last received value (lossy hold).

        Gated sequence numbers count transmissions, so a sequence gap means
        actual missing data, not intentional suppression. Never bridge that
        gap, a restart, or a switch from the continuous protocol. Work remains
        bounded to one window even after hours without significant motion.
        """
        elapsed = (None if self.last_gated_timestamp is None else
                   (packet.timestamp_ms - self.last_gated_timestamp) & 0xffffffff)
        if (elapsed is None or elapsed == 0 or elapsed >= 0x80000000
                or packet.sequence != self.expected_seq
                or packet.features[-1] & STREAM_START):
            self.buffer.clear()
            self.step_counter = 0
        elif self.buffer:
            slots = max(1, (elapsed + SAMPLE_PERIOD_MS // 2) // SAMPLE_PERIOD_MS)
            missing = min(slots - 1, self.window_size - 1)
            self.buffer.extend([self.buffer[-1]] * missing)
            self.step_counter += missing
        self.last_gated_timestamp = packet.timestamp_ms
        self.expected_seq = (packet.sequence + 1) & 0xffffffff
        # Emit only at the real packet, not a burst of stale synthetic windows.
        self._push_and_emit(converted, packet.sequence, packet.timestamp_ms)

    def _push_and_emit(self, frame: list, sequence, timestamp_ms):
        self.buffer.append(frame)
        self.step_counter += 1

        if len(self.buffer) == self.window_size and self.step_counter >= self.hop_size:
            matrix = np.array(self.buffer, dtype=np.float32)
            matrix.setflags(write=False)
            window = InferenceWindow(matrix, sequence, timestamp_ms,
                                     self.received_at, time.monotonic())
            try:
                self.output_queue.put_nowait(window)
            except Full:
                self.output_queue.get_nowait()
                self.output_queue.put_nowait(window)

            self.step_counter = 0
