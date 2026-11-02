"""Passive packet-health and RTT statistics shared by live dashboards."""

from collections import deque
import struct
import zlib


class TelemetryHealth:
    """Track sample arrivals; MQTT presence alone does not prove data is flowing."""

    def __init__(self, started_at, silence_timeout=2.0):
        self.started_at = started_at
        self.silence_timeout = silence_timeout
        self.last_seen = None
        self.last_sequence = None
        self.last_timestamp = None
        self.presence = "unknown"
        self.silent = False
        self.outages = 0
        self.recoveries = 0
        self.last_gap = None
        self.arrivals = deque(maxlen=10000)
        self.events = deque(maxlen=256)
        self.events_evicted = 0

    def event(self, now, name, detail):
        if len(self.events) == self.events.maxlen:
            self.events_evicted += 1
        self.events.append((now - self.started_at, name, detail))

    def check(self, now):
        if (self.last_seen is not None and not self.silent
                and now - self.last_seen >= self.silence_timeout):
            self.silent = True
            self.outages += 1
            self.event(now, "telemetry_timeout", f"No samples for {now - self.last_seen:.3f}s")
            return True
        return False

    def observe(self, now, sequence, timestamp):
        # Also check here so a returning packet cannot hide a timeout between
        # dashboard refreshes.
        self.check(now)
        resync = self.silent
        if self.silent:
            self.last_gap = now - self.last_seen
            self.recoveries += 1
            self.event(now, "telemetry_resumed", f"Gap between samples: {self.last_gap:.3f}s")
        elif self.last_seen is None:
            self.event(now, "first_telemetry", "First sample received")

        # Both counters going backwards suggests a reboot. Modular comparisons
        # allow the normal uint32 wrap; this is not proof of a hardware reset.
        if (self.last_sequence is not None
                and (sequence - self.last_sequence) % (1 << 32) > (1 << 31)
                and (timestamp - self.last_timestamp) % (1 << 32) > (1 << 31)):
            self.event(now, "clock_restart_suspected", "Sample index and device clock moved backwards")
            resync = True

        self.last_seen = now
        self.last_sequence = sequence
        self.last_timestamp = timestamp
        self.silent = False
        self.arrivals.append(now)
        self._prune(now)
        return resync

    def set_presence(self, now, state, retained=False):
        # A retained value predates our subscription and is not a fresh event.
        if retained and self.last_seen is not None:
            return False
        changed = state != self.presence
        self.presence = state
        if changed:
            source = "retained snapshot" if retained else "live broker message"
            self.event(now, "mqtt_presence", f"{state} ({source})")
        return not retained and state in ("online", "offline")

    def _prune(self, now):
        while self.arrivals and self.arrivals[0] <= now - 1.0:
            self.arrivals.popleft()

    def snapshot(self, now):
        self._prune(now)
        age = None if self.last_seen is None else now - self.last_seen
        state = "WAITING" if age is None else (
            "NO DATA" if age >= self.silence_timeout else "RECEIVING"
        )
        return state, age, len(self.arrivals)


class TelemetryRtt:
    """Receive bounded cumulative snapshots measured on the FireBeetle clock.

    Mean/min/max/count are for the current device MQTT connection. Estimated
    one-way latency is half the mean RTT. Slow samples are retained;
    missing ACKs are separate timeouts, never invented latency measurements.
    """
    REQUEST_FLAG = 0x80
    HEADER = struct.Struct("<4sIIIQIIIIIII")
    CRC = struct.Struct("<I")
    TIMEOUT_US = 15_000_000

    def __init__(self):
        self.session = None
        self.report_index = None
        self.last_seen = None
        self.samples = 0
        self.total_us = 0
        self.minimum_us = self.maximum_us = None
        self.timeouts = self.cancelled = self.publish_failures = self.late_acks = 0
        self.pending = False
        self.invalid_reports = 0
        self.ack_errors = 0
        self.last_ack = None

    def set_session(self, session):
        if type(session) is not int or not 0 <= session <= 0xffffffff:
            return
        if self.session != session:
            self.session = session
            self.report_index = self.last_seen = None
            self.samples = self.total_us = 0
            self.minimum_us = self.maximum_us = None
            self.timeouts = self.cancelled = self.publish_failures = self.late_acks = 0
            self.pending = False
            self.last_ack = None

    def acknowledge(self, client, topic, packet, payload):
        # Only CRC-checked packets explicitly marked by the board receive ACKs.
        # No reply is generated for the other ~199 packets in a two-second span.
        if not packet.checked or not packet.features[-1] & self.REQUEST_FLAG:
            return
        ack = payload[:8] + payload[-4:]
        if ack == self.last_ack:
            return
        if client.publish(topic, ack).rc == 0:
            self.last_ack = ack
        else:
            self.ack_errors += 1

    def receive(self, payload, retained, now):
        if retained:
            return False
        expected_size = self.HEADER.size + self.CRC.size
        if (len(payload) != expected_size or
                self.CRC.unpack_from(payload, expected_size - 4)[0] != zlib.crc32(payload[:-4])):
            self.invalid_reports += 1
            return False
        (magic, session, index, samples, total, minimum, maximum, timeouts,
         cancelled, failures, late, pending) = self.HEADER.unpack_from(payload)
        if self.session is None or session != self.session:
            return False # Wait for the current connection's status, reject stale sessions.
        if self.report_index is not None and not 0 < ((index - self.report_index) & 0xffffffff) < 0x80000000:
            return False
        if (magic != b"RTT1" or pending > 1
                or samples < self.samples or total < self.total_us
                or (samples == 0 and (minimum or maximum or total))
                or (samples > 0 and not 0 <= minimum <= maximum < self.TIMEOUT_US)
                or not samples * minimum <= total <= samples * maximum):
            self.invalid_reports += 1
            return False
        self.report_index, self.last_seen = index, now
        self.samples, self.total_us = samples, total
        self.minimum_us = minimum if samples else None
        self.maximum_us = maximum if samples else None
        self.timeouts, self.cancelled = timeouts, cancelled
        self.publish_failures, self.late_acks = failures, late
        self.pending = bool(pending)
        return True

    @property
    def mean_ms(self):
        return self.total_us / self.samples / 1000 if self.samples else None

    @property
    def estimated_one_way_ms(self):
        return self.mean_ms / 2 if self.samples else None
