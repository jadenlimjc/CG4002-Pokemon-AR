import os
import argparse
import csv
import fcntl
import json
import math
import logging
import shutil
import sys
import time
import struct
import zlib
import select
import termios
import tty
from collections import deque
from pathlib import Path
from threading import RLock
from datetime import datetime
from contextlib import contextmanager
from uuid import uuid4

# Support direct execution from tests/ or any other working directory.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from process_telemetry import PacketError, SequenceStats, decode_packet, TelemetryBuffer
from file_transfer import TransferController

from main import (
    TelemetryProcessor,
    create_mqtt_client,
    connect_with_retry,
    BROKER_HOST,
    BROKER_PORT,
    InferenceWorker,
    validate_model_id,
)

LOG_DIR = os.path.abspath(os.path.dirname(__file__))
LOG_FILE = os.path.join(LOG_DIR, "telemetry_rtt_results.csv")
EVENT_FILE = os.path.join(LOG_DIR, "telemetry.log")


RESULT_FIELDS = [
    "Timestamp", "Total Packets", "Duration (s)", "Throughput (Hz)",
    "RTT mean (ms)", "Est. one-way (ms)", "RTT min (ms)", "RTT max (ms)",
    "RTT samples", "RTT session", "RTT report age (s)", "RTT timeouts", "RTT cancelled",
    "RTT publish failures", "RTT late ACKs", "RTT invalid reports", "RTT ACK publish errors",
    "Received messages", "CRC checked", "Unchecked", "Bad CRC", "Bad length",
    "Gap slots", "Repeats", "Backwards/reset", "Retained ignored",
    "Event history omitted", "Missing CRC", "CRC required", "Silences", "Recoveries",
    "Last gap (s)", "Model ID", "Skipped inference windows",
    "Accepted payload bytes", "Payload throughput (kbps)",
]


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


class DashboardLogFilter(logging.Filter):
    def __init__(self, dashboard):
        super().__init__()
        self.dashboard = dashboard

    def filter(self, record):
        self.dashboard.last_log_msg = f"[{record.levelname}] {record.getMessage()}"
        # The UI thread renders logs; MQTT callbacks must not move the cursor.
        return False


class DeviceMonitor:
    def __init__(self, processor: TelemetryProcessor, silence_timeout=2.0, require_crc=False,
                 file_path=None, output_dir=None):
        self.processor = processor
        self.topics = processor.topics
        self.lock = RLock()
        self.health = TelemetryHealth(time.monotonic(), silence_timeout)
        self.demo = TransferController(processor.client, processor.model_id,
                                   file_path or Path(LOG_DIR) / "demo_file.txt",
                                   output_dir or Path(LOG_DIR) / "received_files",
                                   lambda name, detail: self.health.event(time.monotonic(), name, detail))
        self.payload_bytes = 0
        self.recent_bytes = deque()
        self.broker_online = False
        self.packet_count = 0
        self.rtt = TelemetryRtt()
        self.sequences = SequenceStats()
        self.received_messages = 0
        self.checked_packets = 0
        self.unchecked_packets = 0
        self.bad_length = 0
        self.bad_crc = 0
        self.missing_crc = 0
        self.require_crc = require_crc
        self.retained_packets = 0

        self.first_packet_time = None
        self.first_packet_monotonic = None
        self.last_action_msg = "Ready (Press key options below)"
        self.last_log_msg = "No messages yet"

    def on_message(self, client, userdata, msg):
        with self.lock:
            payload = self._on_message(client, msg)
        # Inference does not need the dashboard/statistics lock.
        if payload is not None:
            self.processor.process_packet(payload)

    def on_connect(self, client, userdata, flags, reason_code, properties):
        with self.lock:
            self.broker_online = reason_code == 0
            self.health.event(time.monotonic(), "broker_connection", str(reason_code))

    def on_disconnect(self, client, userdata, flags, reason_code, properties):
        with self.lock:
            self.broker_online = False
            self.demo.disconnected()
            self.health.event(time.monotonic(), "broker_disconnected", str(reason_code))

    def _on_message(self, client, msg):
        now = time.monotonic()

        suffix = msg.topic.rsplit("/", 1)[-1]
        if suffix in ("mode", "demo_out"):
            old_mode = self.demo.mode
            self.demo.on_message(suffix, msg.payload, msg.retain)
            if self.demo.mode != old_mode:
                self.processor.buffer = TelemetryBuffer()
                self.health.last_seen = None
                self.health.silent = False
                self.health.arrivals.clear()
                self.recent_bytes.clear()
                self.sequences.last_sequence = None
            return
        if msg.topic == self.topics["haptic"]:
            if not msg.retain and self.demo.mode in ("file", "pipeline"):
                self.demo.trigger()
            return
        if msg.topic == self.topics["status"]:
            try:
                status = json.loads(msg.payload)
                state = status.get("state")
            except (ValueError, AttributeError, UnicodeError):
                logging.warning("Ignoring invalid FireBeetle status message")
                return
            if state in ("online", "offline"):
                previous = self.health.presence
                if state == "online":
                    self.rtt.set_session(status.get("rtt_session"))
                if self.health.set_presence(now, state, msg.retain):
                    if state == "offline" or previous != "online":
                        self.demo.disconnected()
            return

        if msg.topic == self.topics["rtt"]:
            if self.health.presence != "offline" and self.rtt.receive(msg.payload, msg.retain, now):
                self.health.event(now, "telemetry_rtt", f"session={self.rtt.session:08x}; "
                                  f"samples={self.rtt.samples}; mean_ms={self.rtt.mean_ms}; "
                                  f"estimated_one_way_ms={self.rtt.estimated_one_way_ms}; "
                                  f"timeouts={self.rtt.timeouts}; cancelled={self.rtt.cancelled}")
            return

        # -----------------------------------------------------
        # Telemetry throughput, sparse acknowledgements and pipeline forwarding
        # -----------------------------------------------------
        if msg.topic == self.topics["telemetry"]:
            self.received_messages += 1
            if msg.retain:
                self.retained_packets += 1
                return
            try:
                packet = decode_packet(msg.payload, require_crc=self.require_crc)
            except PacketError as error:
                if error.kind == "bad_crc":
                    self.bad_crc += 1
                elif error.kind == "missing_crc":
                    self.missing_crc += 1
                else:
                    self.bad_length += 1
                return
            if packet.checked:
                self.checked_packets += 1
            else:
                self.unchecked_packets += 1
            # ACK before inference and sequence bookkeeping. It only echoes
            # this packet's identity; the FireBeetle measures elapsed time.
            self.rtt.acknowledge(client, self.topics["ack"], packet, msg.payload)
            if not self.sequences.observe(packet):
                return
            sequence, esp_timestamp = packet.sequence, packet.timestamp_ms
            self.health.observe(now, sequence, esp_timestamp)
            if self.packet_count == 0:
                self.first_packet_time = time.time() * 1000
                self.first_packet_monotonic = now
            self.packet_count += 1
            self.payload_bytes += len(msg.payload)
            self.recent_bytes.append((now, len(msg.payload)))
            while self.recent_bytes and self.recent_bytes[0][0] <= now - 1:
                self.recent_bytes.popleft()
            return msg.payload if self.demo.mode == "auto" else None

    def tick(self, client):
        with self.lock:
            now = time.monotonic()
            self.demo.tick(self.broker_online and self.health.presence != "offline")
            if self.demo.mode != "auto":
                return
            self.health.check(now)

    def _stats_lines(self):
        self.last_action_msg = self.demo.message
        now = time.monotonic()
        while self.recent_bytes and self.recent_bytes[0][0] <= now - 1:
            self.recent_bytes.popleft()
        current_kbps = sum(size for _, size in self.recent_bytes) * 8 / 1000

        elapsed_sec = (
            (time.monotonic() - self.first_packet_monotonic)
            if self.first_packet_monotonic is not None
            else 0.0
        )
        hz = (self.packet_count / elapsed_sec) if elapsed_sec > 0 else 0
        state, age, current_hz = self.health.snapshot(time.monotonic())
        if self.demo.mode in ("file", "pipeline"):
            state = "MANUAL (stream paused)"
        age_text = "never" if age is None else f"{age:.1f}s ago"
        broker = "connected" if self.broker_online else "DISCONNECTED"
        gap = "--" if self.health.last_gap is None else f"{self.health.last_gap:.2f}s"
        show_ms = lambda value: "--" if value is None else f"{value:.2f}"
        rtt_age = "no report yet" if self.rtt.last_seen is None else f"report {now-self.rtt.last_seen:.1f}s ago"
        rtt_min = self.rtt.minimum_us / 1000 if self.rtt.minimum_us is not None else None
        rtt_max = self.rtt.maximum_us / 1000 if self.rtt.maximum_us is not None else None
        rate_prefix = ">=" if current_hz == self.health.arrivals.maxlen else ""

        lines = [
            f" FireBeetle: {self.processor.model_id} | Mode: {(self.demo.mode or 'unconfirmed').upper()}",
            f" Telemetry: {state} | Last: {age_text}",
            f" Broker: {broker} | Device status: {self.health.presence}",
            f" Silences: {self.health.outages} | Returns: {self.health.recoveries} | Last gap: {gap}",
            f" Rate: {rate_prefix}{current_hz} Hz | Payload: {current_kbps:.2f} kbps (last 1s)",
            f" Session avg: {hz:.1f} Hz | {self.payload_bytes * 8 / elapsed_sec / 1000 if elapsed_sec > 0 else 0:.2f} kbps",
            f" RTT ms: mean {show_ms(self.rtt.mean_ms)} | min {show_ms(rtt_min)} | max {show_ms(rtt_max)}",
            f" Est. one-way: {show_ms(self.rtt.estimated_one_way_ms)} ms (mean RTT / 2) | {rtt_age}",
            f" Device-session RTT samples: {self.rtt.samples} | Timeouts: {self.rtt.timeouts} | Cancelled: {self.rtt.cancelled}",
            f" Packets: {self.packet_count} | ACK errors: {self.rtt.ack_errors} | Bad RTT reports: {self.rtt.invalid_reports}",
            f" CRC checked: {self.checked_packets} | Unchecked: {self.unchecked_packets}",
            f" Bad CRC: {self.bad_crc} | Length: {self.bad_length} | Missing CRC: {self.missing_crc}",
            f" Gaps: {self.sequences.gap_slots} | Repeats: {self.sequences.duplicates} | Back/reset: {self.sequences.backwards}",
            f" Last Action     : {self.last_action_msg}",
            f" Last Log        : {self.last_log_msg}",
            " [c/1] Mode | [s/Space] Send via FireBeetle to phone",
            " [h/2] Haptic (Send in manual mode) | [Tab] Device",
            " [q / ^C] Stop Demo & Save Log",
        ]

        if self.demo.last_result and "sha256" in self.demo.last_result:
            result = self.demo.last_result
            lines.insert(3, f" File PASS: {result['bytes']} bytes | {result['kbps']:.2f} kbps round-trip goodput")
            lines.insert(4, f" SHA256: {result['sha256']}")
        return lines

    def log_final_metrics(self, ended=None):
        # RTT snapshots are cumulative for the board's current MQTT session.
        # Save their age so stale results cannot be mistaken for live samples.
        ended = ended or datetime.now().isoformat(timespec="microseconds")
        elapsed = (time.monotonic() - self.first_packet_monotonic
                   if self.first_packet_monotonic is not None else 0.0)
        row = {
            "Timestamp": ended,
            "Model ID": self.processor.model_id,
            "Skipped inference windows": self.processor.skipped_windows,
            "Total Packets": self.packet_count,
            "Accepted payload bytes": self.payload_bytes,
            "Payload throughput (kbps)": f"{self.payload_bytes * 8 / elapsed / 1000:.3f}" if elapsed > 0 else "0.000",
            "Duration (s)": f"{elapsed:.2f}",
            "Throughput (Hz)": f"{self.packet_count / elapsed:.2f}" if elapsed > 0 else "0.00",
            "RTT mean (ms)": f"{self.rtt.mean_ms:.3f}" if self.rtt.samples else "",
            "Est. one-way (ms)": f"{self.rtt.estimated_one_way_ms:.3f}" if self.rtt.samples else "",
            "RTT min (ms)": f"{self.rtt.minimum_us / 1000:.3f}" if self.rtt.samples else "",
            "RTT max (ms)": f"{self.rtt.maximum_us / 1000:.3f}" if self.rtt.samples else "",
            "RTT samples": self.rtt.samples,
            "RTT session": f"{self.rtt.session:08x}" if self.rtt.session is not None else "",
            "RTT report age (s)": f"{time.monotonic()-self.rtt.last_seen:.3f}" if self.rtt.last_seen is not None else "",
            "RTT timeouts": self.rtt.timeouts,
            "RTT cancelled": self.rtt.cancelled,
            "RTT publish failures": self.rtt.publish_failures,
            "RTT late ACKs": self.rtt.late_acks,
            "RTT invalid reports": self.rtt.invalid_reports,
            "RTT ACK publish errors": self.rtt.ack_errors,
            "Received messages": self.received_messages,
            "CRC checked": self.checked_packets,
            "Unchecked": self.unchecked_packets,
            "Bad CRC": self.bad_crc,
            "Bad length": self.bad_length,
            "Gap slots": self.sequences.gap_slots,
            "Repeats": self.sequences.duplicates,
            "Backwards/reset": self.sequences.backwards,
            "Retained ignored": self.retained_packets,
            "Event history omitted": self.health.events_evicted,
            "Missing CRC": self.missing_crc,
            "CRC required": self.require_crc,
            "Silences": self.health.outages,
            "Recoveries": self.health.recoveries,
            "Last gap (s)": f"{self.health.last_gap:.3f}" if self.health.last_gap is not None else "",
        }
        # Allow separate real-device test sessions to share these same files.
        with open(LOG_FILE, "a+", newline="", encoding="utf-8") as output:
            fcntl.flock(output, fcntl.LOCK_EX)
            output.seek(0)
            header = next(csv.reader(output), None)
            if header is not None and header != RESULT_FIELDS:
                raise ValueError(f"{LOG_FILE} header does not match the current demo")
            output.seek(0, os.SEEK_END)
            writer = csv.DictWriter(output, fieldnames=RESULT_FIELDS)
            if header is None:
                writer.writeheader()
            writer.writerow(row)

        prefix = f"[{ended}] [{self.processor.model_id}]"
        with open(EVENT_FILE, "a", encoding="utf-8") as output:
            fcntl.flock(output, fcntl.LOCK_EX)
            output.write(f"{prefix} run_ended: {self.packet_count} accepted samples\n")
            for elapsed, event, detail in self.health.events:
                output.write(f"{prefix} +{elapsed:.3f}s {event}: {detail}\n")
            if self.health.events_evicted:
                output.write(f"{prefix} event_history_truncated: "
                             f"{self.health.events_evicted} older events omitted; totals preserved\n")
        print(f"\n[+] Run summary: {LOG_FILE}\n[+] Connection events: {EVENT_FILE}")


class TelemetryDashboard:
    """Discover and monitor boards while the UI reads stable registry snapshots."""

    SUBSCRIPTIONS = ("esp32/+/telemetry", "esp32/+/status", "esp32/+/rtt",
                     "esp32/+/mode", "esp32/+/demo_out", "esp32/+/haptic/cmd")

    def __init__(self, client, worker, silence_timeout=2.0, require_crc=False,
                 max_devices=64, file_path=None, output_dir=None):
        self.client = client
        self.worker = worker
        self.silence_timeout = silence_timeout
        self.require_crc = require_crc
        self.max_devices = max_devices
        self.file_path, self.output_dir = file_path, output_dir
        self.lock = RLock()
        self.benchmarks = {}
        self.broker_online = False
        self.selected = 0
        self.last_log_msg = "Waiting for devices"

    def boards(self):
        with self.lock:
            return list(self.benchmarks.values())

    def on_connect(self, client, userdata, flags, reason_code, properties):
        self.broker_online = reason_code == 0
        if self.broker_online:
            for topic in self.SUBSCRIPTIONS:
                client.subscribe(topic)
        for benchmark in self.boards():
            benchmark.on_connect(client, userdata, flags, reason_code, properties)

    def on_disconnect(self, client, userdata, flags, reason_code, properties):
        self.broker_online = False
        for benchmark in self.boards():
            benchmark.on_disconnect(client, userdata, flags, reason_code, properties)

    def on_message(self, client, userdata, msg):
        parts = msg.topic.split("/")
        if (len(parts) not in (3, 4) or parts[0] != "esp32"
                or "/".join(parts[2:]) not in ("telemetry", "status", "rtt", "mode", "demo_out", "haptic/cmd")):
            return
        try:
            model_id = validate_model_id(parts[1])
        except ValueError:
            return
        with self.lock:
            benchmark = self.benchmarks.get(model_id)
            if benchmark is None:
                # Old telemetry and unsolicited reports must not invent live boards.
                if parts[2] not in ("status", "telemetry") or (parts[2] == "telemetry" and msg.retain):
                    return
                if parts[2] == "status":
                    try:
                        if json.loads(msg.payload).get("state") not in ("online", "offline"):
                            return
                    except (ValueError, AttributeError, UnicodeError):
                        return
                if len(self.benchmarks) >= self.max_devices:
                    logging.warning("Device limit reached; ignoring %s", model_id)
                    return
                processor = TelemetryProcessor(client, model_id, self.worker)
                benchmark = DeviceMonitor(processor, self.silence_timeout, self.require_crc,
                                               self.file_path, self.output_dir)
                benchmark.broker_online = self.broker_online
                benchmark.health.event(time.monotonic(), "device_discovered", msg.topic)
                self.benchmarks[model_id] = benchmark
                logging.info("Discovered FireBeetle %s", model_id)
        benchmark.on_message(client, userdata, msg)

    def tick(self):
        for board in self.boards():
            board.tick(self.client)

    def handle_key(self, key):
        if key == "q":
            return False
        boards = self.boards()
        if not boards:
            return True
        if key == "\t":
            self.selected = (self.selected + 1) % len(boards)
        benchmark = boards[self.selected]
        with benchmark.lock:
            if key in ("1", "c"):
                benchmark.demo.cycle_mode()
            elif key in ("s", " "):
                benchmark.demo.trigger()
            elif key in ("2", "h"):
                benchmark.processor.trigger_haptic("1")
        return True

    def stats_lines(self, terminal_height=24):
        boards = self.boards()
        broker = "connected" if self.broker_online else "DISCONNECTED"
        lines = [f" Broker: {broker} | Discovered devices: {len(boards)}"]
        if not boards:
            return lines + [" Waiting for ESP32 telemetry or status...", " [q / ^C] Stop Demo"]
        benchmark = boards[self.selected]
        with benchmark.lock:
            benchmark.last_log_msg = self.last_log_msg
            details = benchmark._stats_lines()
        # Keep the selected ID and controls visible even with many boards.
        visible = max(1, terminal_height - len(details) - 3)
        start = (self.selected // visible) * visible
        for index in range(start, min(start + visible, len(boards))):
            marker = ">" if index == self.selected else " "
            board = boards[index]
            with board.lock:
                state, _, _ = board.health.snapshot(time.monotonic())
                lines.append(f" {marker} {index + 1}. {board.processor.model_id} | {state} | status: {board.health.presence}")
        if len(boards) > visible:
            lines.append(f" Showing {start + 1}-{min(start + visible, len(boards))} of {len(boards)}; Tab cycles all IDs")
        return lines + details

    def print_live_stats(self):
        size = shutil.get_terminal_size()
        lines = self.stats_lines(size.lines)
        # The alternate screen handles a changing number of discovered boards.
        sys.stdout.write("\033[H")
        for line in lines:
            line = "".join(char if char.isprintable() else " " for char in line)
            line = line.encode("ascii", errors="replace").decode("ascii")
            sys.stdout.write(f"\r{line[:max(1, size.columns - 1)]}\033[K\n")
        sys.stdout.write("\033[J")
        sys.stdout.flush()

    @contextmanager
    def dashboard_logging(self):
        log_filter = DashboardLogFilter(self)
        console_handlers = [
            handler for handler in logging.getLogger().handlers
            if isinstance(handler, logging.StreamHandler)
            and not isinstance(handler, logging.FileHandler)
            and handler.stream in (sys.stdout, sys.stderr)
        ]
        for handler in console_handlers:
            handler.addFilter(log_filter)
        try:
            yield
        finally:
            for handler in console_handlers:
                handler.removeFilter(log_filter)


def get_key_non_blocking():
    if select.select([sys.stdin], [], [], 0) == ([sys.stdin], [], []):
        return sys.stdin.read(1)
    return None


def positive_seconds(value):
    seconds = float(value)
    if not math.isfinite(seconds) or seconds <= 0:
        raise argparse.ArgumentTypeError("must be a finite number greater than zero")
    return seconds


def main():
    parser = argparse.ArgumentParser(description="Live FireBeetle demo: automatic telemetry, verified file transfer, and the complete pipeline")
    parser.add_argument("--silence-timeout", type=positive_seconds, default=2.0,
                        help="seconds without telemetry before NO DATA (default: 2)")
    parser.add_argument("--require-crc", action="store_true",
                        help="reject legacy packets without a CRC (use after updating firmware)")
    parser.add_argument("--file", type=Path, default=Path(LOG_DIR) / "demo_file.txt",
                        help="file sent to FireBeetle, re-read on every Send (1..65536 bytes)")
    parser.add_argument("--output-dir", type=Path, default=Path(LOG_DIR) / "received_files",
                        help="directory for files reconstructed from FireBeetle replies")
    args = parser.parse_args()
    if not sys.stdin.isatty():
        parser.error("the live device dashboard requires an interactive terminal")
    client = create_mqtt_client("comms-demo-" + uuid4().hex[:8])
    worker = InferenceWorker()
    dashboard = TelemetryDashboard(client, worker, args.silence_timeout, args.require_crc,
                                   file_path=args.file, output_dir=args.output_dir)
    client.on_message = dashboard.on_message
    client.on_connect = dashboard.on_connect
    client.on_disconnect = dashboard.on_disconnect
    old_settings = termios.tcgetattr(sys.stdin)
    try:
        connect_with_retry(client, BROKER_HOST, BROKER_PORT)
        tty.setcbreak(sys.stdin.fileno())
        sys.stdout.write("\033[?1049h\033[2J\033[H")
        with dashboard.dashboard_logging():
            worker.start()
            client.loop_start()
            try:
                while True:
                    dashboard.tick()
                    if not dashboard.handle_key(get_key_non_blocking()):
                        break
                    dashboard.print_live_stats()
                    time.sleep(0.1)
            finally:
                client.loop_stop()
                worker.close()
                client.disconnect()
    except KeyboardInterrupt:
        pass
    finally:
        client.loop_stop()
        worker.close()
        client.disconnect()
        sys.stdout.write("\033[?1049l")
        sys.stdout.flush()
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)
        print("\n\n[!] Demo stopped.")
        ended = datetime.now().isoformat(timespec="microseconds")
        for benchmark in dashboard.boards():
            benchmark.log_final_metrics(ended)


if __name__ == "__main__":
    main()
