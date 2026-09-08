from collections import deque
from queue import Full, Queue
import struct
import numpy as np

# Binary format: uint32, 6x int16, uint16, uint8 = 19 bytes (Little-Endian)
PACKET_FORMAT = "<IhhhhhhHB"
PACKET_SIZE = struct.calcsize(PACKET_FORMAT)

ACCEL_SCALE = 2.0 / 32768.0  # Range +-2g
GYRO_SCALE = 250.0 / 32768.0  # Range +-250 dps


class TelemetryBuffer:
    def __init__(self, window_size=20, hop_size=10, max_gap_fill=5, queue_maxsize=10):
        self.window_size = window_size
        self.hop_size = hop_size
        self.step_counter = 0
        self.max_gap_fill = max_gap_fill
        self.output_queue = Queue(maxsize=queue_maxsize)
        self.buffer = deque(maxlen=window_size)
        self.expected_seq = None

    def _convert_units(self, raw_readings: tuple) -> list:
        ax, ay, az, gx, gy, gz, hall_raw, flags = raw_readings
        hall_trigger = flags & 0x01

        return [
            ax * ACCEL_SCALE,
            ay * ACCEL_SCALE,
            az * ACCEL_SCALE,
            gx * GYRO_SCALE,
            gy * GYRO_SCALE,
            gz * GYRO_SCALE,
            float(hall_raw),
            float(hall_trigger),
        ]

    def add_packet(self, payload: bytes):
        if len(payload) != PACKET_SIZE:
            return

        unpacked = struct.unpack(PACKET_FORMAT, payload)
        sample_index = unpacked[0]
        raw_features = unpacked[1:]

        converted = self._convert_units(raw_features)

        if self.expected_seq is None:
            self.expected_seq = sample_index

        gap = sample_index - self.expected_seq

        if gap == 0:
            self._push_and_emit(converted)
            self.expected_seq = sample_index + 1

        elif 0 < gap <= self.max_gap_fill:
            # Pad missing sequence slots with last known frame
            last_frame = self.buffer[-1] if len(self.buffer) > 0 else converted
            for _ in range(gap):
                self._push_and_emit(last_frame)
            self._push_and_emit(converted)
            self.expected_seq = sample_index + 1

        else:
            # Large sequence jump: Reset window
            self.buffer.clear()
            self.step_counter = 0
            self._push_and_emit(converted)
            self.expected_seq = sample_index + 1

    def _push_and_emit(self, frame: list):
        self.buffer.append(frame)
        self.step_counter += 1

        # if len(self.buffer) == self.window_size:
        if len(self.buffer) == self.window_size and self.step_counter >= self.hop_size:
            matrix = np.array(self.buffer, dtype=np.float32)
            try:
                self.output_queue.put_nowait(matrix)
            except Full:
                self.output_queue.get_nowait()
                self.output_queue.put_nowait(matrix)

            self.step_counter = 0
