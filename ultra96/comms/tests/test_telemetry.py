"""Real ESP32/FireBeetle <-> Ultra96 telemetry and command test.

Run on the Ultra96 with the broker and ESP32 firmware running:
    python3 ultra96/comms/tests/test_telemetry.py --model-id ID1 ID2 --require-crc

Read each board's model ID from its boot serial output. Run this test instead
of main.py to avoid duplicate inference. All selected boards are monitored
concurrently; Tab changes the board targeted by the dashboard and commands.
Uses main.py's broker settings and MQTT credentials. The dashboard measures
packet integrity, rate, latency, silence and recovery; c sends configuration,
h sends a haptic command, and q saves results and exits. Verify the commands
on the physical ESP32. The main pipeline's inference is still a placeholder.

Appends one summary per board per run to telemetry_results.csv and connection/clock
events to telemetry.log beside this script. Unsynced latency stays blank.
"""

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
from process_telemetry import PacketError, SequenceStats, decode_packet

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
LOG_FILE = os.path.join(LOG_DIR, "telemetry_results.csv")
EVENT_FILE = os.path.join(LOG_DIR, "telemetry.log")


RESULT_FIELDS = [
    "Timestamp", "Total Packets", "Duration (s)", "Throughput (Hz)",
    "Avg Latency (ms)", "Min Latency (ms)", "Max Latency (ms)", "Clock Offset (ms)",
    "Received messages", "CRC checked", "Unchecked", "Bad CRC", "Bad length",
    "Gap slots", "Repeats", "Backwards/reset", "Retained ignored", "Latency samples",
    "Event history omitted", "Missing CRC", "CRC required", "Silences", "Recoveries",
    "Last gap (s)", "Model ID", "Skipped inference windows",
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


class RunningLatency:
    """Constant-space, constant-work lifetime count/mean/min/max."""
    def __init__(self):
        self.count = 0
        self.mean = 0.0
        self.minimum = None
        self.maximum = None

    def add(self, value):
        self.count += 1
        self.mean += (value - self.mean) / self.count
        self.minimum = value if self.minimum is None else min(self.minimum, value)
        self.maximum = value if self.maximum is None else max(self.maximum, value)


class DashboardLogFilter(logging.Filter):
    def __init__(self, benchmark):
        super().__init__()
        self.benchmark = benchmark

    def filter(self, record):
        self.benchmark.last_log_msg = f"[{record.levelname}] {record.getMessage()}"
        # The UI thread renders logs; MQTT callbacks must not move the cursor.
        return False


class TelemetryBenchmark:
    def __init__(self, processor: TelemetryProcessor, silence_timeout=2.0, require_crc=False):
        self.processor = processor
        self.topics = processor.topics
        self.lock = RLock()
        self.health = TelemetryHealth(time.monotonic(), silence_timeout)
        self.broker_online = False
        self.packet_count = 0
        self.ping_sent_time = None
        self.ping_sent_monotonic = None
        self.clock_offset = None
        self.latency = RunningLatency()
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
        self.is_first_print = True
        self.last_action_msg = "Ready (Press key options below)"
        self.last_log_msg = "No messages yet"

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

    def on_message(self, client, userdata, msg):
        with self.lock:
            payload = self._on_message(client, msg)
        # Inference does not need the dashboard/statistics lock.
        if payload is not None:
            self.processor.process_packet(payload)

    def invalidate_clock(self):
        self.clock_offset = None
        self.ping_sent_time = None
        self.ping_sent_monotonic = None

    def on_connect(self, client, userdata, flags, reason_code, properties):
        with self.lock:
            self.broker_online = reason_code == 0
            self.health.event(time.monotonic(), "broker_connection", str(reason_code))
            if self.broker_online:
                # Re-subscribe after broker reconnection as well as startup.
                for topic in (self.topics["pong"], self.topics["telemetry"], self.topics["status"]):
                    client.subscribe(topic)

    def on_disconnect(self, client, userdata, flags, reason_code, properties):
        with self.lock:
            self.broker_online = False
            self.invalidate_clock()
            self.health.event(time.monotonic(), "broker_disconnected", str(reason_code))

    def _on_message(self, client, msg):
        now_ms = time.time() * 1000
        now = time.monotonic()

        if msg.topic == self.topics["status"]:
            try:
                state = json.loads(msg.payload).get("state")
            except (ValueError, AttributeError, UnicodeError):
                logging.warning("Ignoring invalid FireBeetle status message")
                return
            if state in ("online", "offline"):
                if self.health.set_presence(now, state, msg.retain):
                    self.invalidate_clock()
            return

        # -----------------------------------------------------
        # Clock Synchronization
        # -----------------------------------------------------
        if msg.topic == self.topics["pong"]:
            if (msg.retain or len(msg.payload) != 4
                    or self.ping_sent_monotonic is None):
                return
            rtt = (now - self.ping_sent_monotonic) * 1000
            if rtt > 1000:
                return
            esp32_millis = struct.unpack("<I", msg.payload)[0]
            one_way_delay = rtt / 2
            ultra96_time_at_publish = self.ping_sent_time + one_way_delay
            self.clock_offset = ultra96_time_at_publish - esp32_millis
            self.ping_sent_monotonic = None
            self.health.event(now, "clock_synced", f"Offset={self.clock_offset:.2f}ms")
            return

        # -----------------------------------------------------
        # Telemetry Latency Benchmarking & Main Pipeline Forwarding
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
            if not self.sequences.observe(packet):
                return
            sequence, esp_timestamp = packet.sequence, packet.timestamp_ms
            if self.health.observe(now, sequence, esp_timestamp):
                self.invalidate_clock()
            if self.packet_count == 0:
                self.first_packet_time = now_ms
                self.first_packet_monotonic = now
            self.packet_count += 1
            if self.clock_offset is not None:
                esp_time_in_u96_frame = esp_timestamp + self.clock_offset
                absolute_latency = now_ms - esp_time_in_u96_frame
                self.latency.add(absolute_latency)

            return msg.payload

    def tick(self, client):
        with self.lock:
            now = time.monotonic()
            if self.health.check(now):
                self.invalidate_clock()
            state, _, _ = self.health.snapshot(now)
            if (not self.broker_online or self.clock_offset is not None
                    or state == "NO DATA"):
                return
            if (self.ping_sent_monotonic is not None
                    and now - self.ping_sent_monotonic < 1.0):
                return
            self.ping_sent_time = time.time() * 1000
            self.ping_sent_monotonic = now
            client.publish(self.topics["ping"], "sync")

    def print_live_stats(self):
        with self.lock:
            lines = self._stats_lines()

        # Terminal I/O must not block the MQTT thread from updating statistics.
        if not self.is_first_print:
            sys.stdout.write(f"\033[{len(lines)}A")
        self.is_first_print = False
        width = max(1, shutil.get_terminal_size().columns - 1)
        for line in lines:
            line = "".join(char if char.isprintable() else " " for char in line)
            line = line.encode("ascii", errors="replace").decode("ascii")
            sys.stdout.write(f"\r{line[:width]}\033[K\n")
        sys.stdout.flush()

    def _stats_lines(self):
        avg_lat = self.latency.mean
        max_lat = self.latency.maximum or 0.0
        min_lat = self.latency.minimum or 0.0

        elapsed_sec = (
            (time.monotonic() - self.first_packet_monotonic)
            if self.first_packet_monotonic is not None
            else 0.0
        )
        hz = (self.packet_count / elapsed_sec) if elapsed_sec > 0 else 0
        state, age, current_hz = self.health.snapshot(time.monotonic())
        age_text = "never" if age is None else f"{age:.1f}s ago"
        broker = "connected" if self.broker_online else "DISCONNECTED"
        gap = "--" if self.health.last_gap is None else f"{self.health.last_gap:.2f}s"
        clock = "synced" if self.clock_offset is not None else "waiting for sync"
        rate_prefix = ">=" if current_hz == self.health.arrivals.maxlen else ""

        lines = [
            "=" * 44,
            f" FireBeetle: {self.processor.model_id} | Tab: next device",
            f" Telemetry: {state} | Last: {age_text}",
            f" Broker: {broker} | Device status: {self.health.presence}",
            f" Silences: {self.health.outages} | Returns: {self.health.recoveries} | Last gap: {gap}",
            f" Rate (last 1s): {rate_prefix}{current_hz} Hz | Average: {hz:.1f} Hz",
            f" Total Packets: {self.packet_count} | Clock: {clock}",
            "-" * 44,
            f" Latency ms: avg {avg_lat:.2f} | min {min_lat:.2f} | max {max_lat:.2f}",
            f" Latency samples : {self.latency.count} (synced only)",
            f" CRC checked: {self.checked_packets} | Unchecked: {self.unchecked_packets}",
            f" Bad CRC: {self.bad_crc} | Length: {self.bad_length} | Missing CRC: {self.missing_crc}",
            f" Gap slots: {self.sequences.gap_slots} | Repeats: {self.sequences.duplicates}",
            f" Backwards/reset: {self.sequences.backwards} | Retained ignored: {self.retained_packets}",
            "-" * 44,
            f" Last Action     : {self.last_action_msg}",
            f" Last Log        : {self.last_log_msg}",
            "-" * 44,
            f" Skipped inference windows: {self.processor.skipped_windows}",
            " [1 / c] Send config to this device",
            " [2 / h] Send haptic to this device",
            " [q / ^C] Stop Test & Save Log",
            "=" * 44,
        ]

        return lines

    def log_final_metrics(self, ended=None):
        # Called after the MQTT loop stops so summary and events share a run ID.
        ended = ended or datetime.now().isoformat(timespec="microseconds")
        elapsed = (time.monotonic() - self.first_packet_monotonic
                   if self.first_packet_monotonic is not None else 0.0)
        row = {
            "Timestamp": ended,
            "Model ID": self.processor.model_id,
            "Skipped inference windows": self.processor.skipped_windows,
            "Total Packets": self.packet_count,
            "Duration (s)": f"{elapsed:.2f}",
            "Throughput (Hz)": f"{self.packet_count / elapsed:.2f}" if elapsed > 0 else "0.00",
            "Avg Latency (ms)": f"{self.latency.mean:.2f}" if self.latency.count else "",
            "Min Latency (ms)": f"{self.latency.minimum:.2f}" if self.latency.count else "",
            "Max Latency (ms)": f"{self.latency.maximum:.2f}" if self.latency.count else "",
            "Clock Offset (ms)": f"{self.clock_offset:.2f}" if self.clock_offset is not None else "",
            "Received messages": self.received_messages,
            "CRC checked": self.checked_packets,
            "Unchecked": self.unchecked_packets,
            "Bad CRC": self.bad_crc,
            "Bad length": self.bad_length,
            "Gap slots": self.sequences.gap_slots,
            "Repeats": self.sequences.duplicates,
            "Backwards/reset": self.sequences.backwards,
            "Retained ignored": self.retained_packets,
            "Latency samples": self.latency.count,
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
                raise ValueError("telemetry_results.csv header does not match the current test")
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
    parser = argparse.ArgumentParser(description="Real multi-FireBeetle to Ultra96 telemetry, config and haptic test")
    parser.add_argument("--model-id", nargs="+", required=True, type=validate_model_id,
                        help="board IDs printed at boot; monitor all, Tab switches command target")
    parser.add_argument("--silence-timeout", type=positive_seconds, default=2.0,
                        help="seconds without telemetry before NO DATA (default: 2)")
    parser.add_argument("--require-crc", action="store_true",
                        help="reject legacy packets without a CRC (use after updating firmware)")
    args = parser.parse_args()
    if not sys.stdin.isatty():
        parser.error("the live device dashboard requires an interactive terminal")
    client = create_mqtt_client("telemetry-test-" + uuid4().hex[:8])
    worker = InferenceWorker()
    benchmarks = {
        model_id: TelemetryBenchmark(TelemetryProcessor(client, model_id, worker),
                                     args.silence_timeout, args.require_crc)
        for model_id in dict.fromkeys(args.model_id)
    }
    boards = list(benchmarks.values())

    def on_connect(*callback_args):
        for benchmark in boards:
            benchmark.on_connect(*callback_args)

    def on_disconnect(*callback_args):
        for benchmark in boards:
            benchmark.on_disconnect(*callback_args)

    def on_message(cli, userdata, msg):
        parts = msg.topic.split("/")
        if len(parts) == 3 and parts[0] == "esp32":
            benchmark = benchmarks.get(parts[1])
            if benchmark is not None:
                benchmark.on_message(cli, userdata, msg)

    client.on_message = on_message
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    old_settings = termios.tcgetattr(sys.stdin)
    selected = 0
    printed = False
    try:
        connect_with_retry(client, BROKER_HOST, BROKER_PORT)
        tty.setcbreak(sys.stdin.fileno())
        # A common log line includes the source model ID when inference runs.
        with boards[0].dashboard_logging():
            worker.start()
            client.loop_start()
            try:
                while True:
                    for benchmark in boards:
                        benchmark.tick(client)
                    key = get_key_non_blocking()
                    if key == "\t":
                        selected = (selected + 1) % len(boards)
                    benchmark = boards[selected]
                    if key in ("1", "c"):
                        benchmark.processor.send_config()
                        benchmark.last_action_msg = "Sent config to this device"
                    elif key in ("2", "h"):
                        benchmark.processor.trigger_haptic("1")
                        benchmark.last_action_msg = "Sent haptic to this device"
                    elif key == "q":
                        break

                    benchmark.last_log_msg = boards[0].last_log_msg
                    benchmark.is_first_print = not printed
                    benchmark.print_live_stats()
                    printed = True
                    time.sleep(0.1)
            finally:
                client.loop_stop()
                worker.close()
                client.disconnect()
    except KeyboardInterrupt:
        pass
    finally:
        worker.close()
        client.disconnect()
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)
        print("\n\n[!] Benchmark stopped.")
        ended = datetime.now().isoformat(timespec="microseconds")
        for benchmark in boards:
            benchmark.log_final_metrics(ended)


if __name__ == "__main__":
    main()
