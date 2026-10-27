"""Live gesture dashboard: predictions, send decisions, state, and packet health.

Run this instead of main.py/comms_demo.py, so only one service sends gestures
and telemetry ACKs. Uses the production TelemetryProcessor and FPGA worker.
"""

from collections import deque
from contextlib import contextmanager
from datetime import datetime
import json
import logging
from pathlib import Path
import select
import shutil
import sys
import termios
import textwrap
from threading import RLock
import time
import tty

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from integration_support import live_client, parser_for
from main import InferenceWorker, TelemetryProcessor, validate_model_id
from process_telemetry import PacketError, SequenceStats, decode_packet
from telemetry_diagnostics import TelemetryHealth, TelemetryRtt
from visualiser_protocol import DEFAULT_CONFIDENCE_THRESHOLD, confidence_threshold


class GestureMonitor:
    """Packet statistics only; production code owns all gesture decisions."""

    def __init__(self, processor, require_crc=False):
        self.processor = processor
        self.require_crc = require_crc
        self.lock = RLock()
        self.health = TelemetryHealth(time.monotonic())
        self.rtt = TelemetryRtt()
        self.sequences = SequenceStats()
        self.received = self.retained = self.packets = self.checked = self.unchecked = 0
        self.bad_crc = self.bad_length = self.missing_crc = 0
        self.payload_bytes = 0
        self.first_packet_at = None
        self.recent_bytes = deque(maxlen=10000)

    def on_message(self, message, now):
        with self.lock:
            accepted = self._observe(message, now)
        if accepted:
            self.processor.process_packet(message.payload, received_at=now)

    def _observe(self, message, now):
        suffix = message.topic.rsplit("/", 1)[-1]
        if suffix == "status":
            try:
                status = json.loads(message.payload)
                state = status.get("state")
            except (ValueError, AttributeError, UnicodeError):
                return False
            if state in ("online", "offline"):
                # Retained snapshots must not replace a newer live session.
                if not message.retain or self.health.last_seen is None:
                    if state == "online":
                        self.rtt.set_session(status.get("rtt_session"))
                    self.health.set_presence(now, state, message.retain)
            return False
        if suffix == "rtt":
            if self.health.presence != "offline":
                self.rtt.receive(message.payload, message.retain, now)
            return False

        self.received += 1
        if message.retain:
            self.retained += 1
            return False
        try:
            packet = decode_packet(message.payload, require_crc=self.require_crc)
        except PacketError as error:
            setattr(self, error.kind, getattr(self, error.kind) + 1)
            return False
        if packet.checked:
            self.checked += 1
        else:
            self.unchecked += 1
        self.rtt.acknowledge(self.processor.client, self.processor.topics["ack"],
                             packet, message.payload)
        if not self.sequences.observe(packet):
            return False
        self.health.observe(now, packet.sequence, packet.timestamp_ms)
        if self.first_packet_at is None:
            self.first_packet_at = now
        self.packets += 1
        self.payload_bytes += len(message.payload)
        self.recent_bytes.append((now, len(message.payload)))
        self._prune(now)
        return True

    def _prune(self, now):
        while self.recent_bytes and self.recent_bytes[0][0] <= now - 1:
            self.recent_bytes.popleft()

    def lines(self, now):
        snapshot = self.processor.inference_snapshot()
        current, sent = snapshot["current"], snapshot["last_sent"]
        lines = [f" STATE: {snapshot['state']} (gesture sequence)"]
        if current is None:
            lines += [" CURRENT: -- waiting for a complete inference window",
                      " DECISION: WAITING; no classification yet"]
        else:
            age = now - snapshot["updated_at"]
            stale = " STALE" if age >= self.health.silence_timeout else ""
            lines += [f" CURRENT: {current['predicted_action']} | {current['confidence']:.2%} | "
                      f"{age:.1f}s ago{stale}",
                      f" DECISION: {current['status']} / {current['reason']}",
                      f" WHY: {current['detail']}"]
        if sent is None:
            lines.append(" LAST SENT: -- no gesture accepted by MQTT yet")
        else:
            stamp = datetime.fromtimestamp(sent["timestamp_ms"] / 1000).strftime("%H:%M:%S")
            lines += [f" LAST SENT: {sent['predicted_action']} -> {sent['action']} "
                      f"(id {sent['gesture_id']})",
                      f" SENT AT: {stamp} | confidence {sent['confidence']:.2%}"]
        lines.append(" SENT = MQTT accepted (QoS 0); AR delivery is unconfirmed.")
        lines.append("")
        with self.lock:
            self.health.check(now)
            self._prune(now)
            state, age, hz = self.health.snapshot(now)
            last = "never" if age is None else f"{age:.1f}s ago"
            elapsed = 0 if self.first_packet_at is None else max(0, now - self.first_packet_at)
            # There are N-1 sample intervals between N received samples.
            average = (self.packets - 1) / elapsed if elapsed > 0 else 0
            kbps = sum(size for _, size in self.recent_bytes) * 8 / 1000
            lines += [f" Telemetry: {state} | last {last} | presence {self.health.presence}",
                      f" Rate: {hz} / 100 Hz expected | avg {average:.1f} Hz | {kbps:.2f} kbps",
                      f" Packets: {self.packets} unique / {self.received} received | retained {self.retained}",
                      f" CRC: {self.checked} checked / {self.unchecked} unchecked | "
                      f"bad {self.bad_crc} / length {self.bad_length} / missing {self.missing_crc}",
                      f" Gaps: {self.sequences.gap_slots} | repeats {self.sequences.duplicates} | "
                      f"back/reset {self.sequences.backwards}",
                      f" Silences: {self.health.outages} | recoveries {self.health.recoveries}"]
            show = lambda value: "--" if value is None else f"{value:.2f}"
            rtt_age = "no report" if self.rtt.last_seen is None else f"{now-self.rtt.last_seen:.1f}s old"
            minimum = None if self.rtt.minimum_us is None else self.rtt.minimum_us / 1000
            maximum = None if self.rtt.maximum_us is None else self.rtt.maximum_us / 1000
            lines += [f" RTT ms: mean {show(self.rtt.mean_ms)} / min {show(minimum)} / "
                      f"max {show(maximum)} ({rtt_age})",
                      f" RTT: {self.rtt.samples} samples | timeouts {self.rtt.timeouts} | "
                      f"ACK errors {self.rtt.ack_errors} | invalid reports {self.rtt.invalid_reports}"]
        if current:
            timing = current["timing_ms"]
            lines.append(f" Timing ms: inference {show(timing['inference'])} | "
                         f"queue {show(timing['queue'])} | receive->result {show(timing['receive_to_result'])}")
        lines.append(f" Window: {len(self.processor.buffer.buffer)}/256 | hop 25 | "
                     f"skipped {self.processor.skipped_windows}")
        counts = snapshot["decision_counts"]
        lines.append(f" Decisions: {sum(counts.values())} | low confidence {counts.get('LOW_CONFIDENCE', 0)} | "
                     f"repeat {counts.get('REPEATED', 0)} | send failed {counts.get('PUBLISH_FAILED', 0)}")
        return lines


class GestureDashboard:
    def __init__(self, client, worker, model_id=None, require_crc=False, max_devices=64):
        self.client, self.worker = client, worker
        self.model_id, self.require_crc = model_id, require_crc
        if max_devices < 1:
            raise ValueError("max_devices must be positive")
        self.max_devices = max_devices
        self.lock = RLock()
        self.monitors = {}
        self.selected = 0
        self.broker_online = False
        self.last_log = "Waiting for telemetry"

    def on_connect(self, client, userdata, flags, reason_code, properties=None):
        self.broker_online = reason_code == 0
        if self.broker_online:
            device = self.model_id or "+"
            client.subscribe([(f"esp32/{device}/{suffix}", 0)
                              for suffix in ("telemetry", "status", "rtt")])
        else:
            logging.error("Broker connection rejected: %s", reason_code)

    def on_disconnect(self, client, userdata, flags, reason_code, properties=None):
        self.broker_online = False

    def on_message(self, client, userdata, message):
        now = time.monotonic()
        parts = message.topic.split("/")
        if len(parts) != 3 or parts[0] != "esp32" or parts[2] not in ("telemetry", "status", "rtt"):
            return
        try:
            device = validate_model_id(parts[1])
        except ValueError:
            return
        if self.model_id is not None and device != self.model_id:
            return
        with self.lock:
            monitor = self.monitors.get(device)
            if monitor is None:
                # Discover on a valid status or fresh valid telemetry, as comms_demo does.
                if parts[2] == "status":
                    try:
                        if json.loads(message.payload).get("state") not in ("online", "offline"):
                            return
                    except (ValueError, AttributeError, UnicodeError):
                        return
                elif parts[2] == "telemetry" and not message.retain:
                    try:
                        decode_packet(message.payload, require_crc=self.require_crc)
                    except PacketError:
                        return
                else:
                    return
                if len(self.monitors) >= self.max_devices:
                    return
                monitor = GestureMonitor(TelemetryProcessor(client, device, self.worker), self.require_crc)
                self.monitors[device] = monitor
        monitor.on_message(message, now)

    def boards(self):
        with self.lock:
            return list(self.monitors.values())

    def handle_key(self, key):
        boards = self.boards()
        if key == "\t" and boards:
            self.selected = (self.selected + 1) % len(boards)
        return key != "q"

    def lines(self, now=None):
        now = time.monotonic() if now is None else now
        boards = self.boards()
        broker = "connected" if self.broker_online else "DISCONNECTED"
        lines = [f" GESTURE TEST | Broker {broker} | threshold {self.worker.confidence_threshold:.2%}"]
        if not boards:
            return lines + [" Waiting for ESP32 telemetry or status..."]
        monitor = boards[self.selected]
        lines.append(f" Device {self.selected + 1}/{len(boards)}: {monitor.processor.model_id}")
        return lines + monitor.lines(now)

    def render(self, width, height):
        lines = []
        for line in self.lines():
            clean = "".join(char if char.isprintable() else " " for char in line)
            wrapped = textwrap.wrap(clean, width=max(1, width - 1),
                                    subsequent_indent="   ", replace_whitespace=False) or [""]
            # Add color after wrapping so ANSI codes do not consume display width.
            color = "\033[1;36m" if clean.startswith(" CURRENT:") else (
                "\033[1;32m" if clean.startswith(" LAST SENT:") else ""
            )
            lines.extend(f"{color}{part}\033[0m" if color else part for part in wrapped)
        footer = " [Tab] Next device | [q / Ctrl-C] Quit"
        if len(lines) > max(0, height - 2):
            lines = lines[:max(0, height - 2)]
            footer = " Resize taller for more stats. [Tab] Device | [q] Quit"
        clean_log = "".join(char if char.isprintable() else " " for char in self.last_log)
        lines += [f" Log: {clean_log}"[:max(1, width - 1)], footer[:max(1, width - 1)]]
        # Write once from the UI thread, clearing obsolete rows each refresh.
        return "\033[H" + "\n".join(line + "\033[K" for line in lines) + "\033[J"

    @contextmanager
    def capture_logs(self):
        dashboard = self

        class DashboardFilter(logging.Filter):
            def filter(self, record):
                dashboard.last_log = f"[{record.levelname}] {record.getMessage()}"
                return False

        handlers = [handler for handler in logging.getLogger().handlers
                    if isinstance(handler, logging.StreamHandler)
                    and not isinstance(handler, logging.FileHandler)
                    and handler.stream in (sys.stdout, sys.stderr)]
        log_filter = DashboardFilter()
        for handler in handlers:
            handler.addFilter(log_filter)
        try:
            yield
        finally:
            for handler in handlers:
                handler.removeFilter(log_filter)


@contextmanager
def terminal_screen():
    settings = termios.tcgetattr(sys.stdin)
    try:
        tty.setcbreak(sys.stdin.fileno())
        sys.stdout.write("\033[?1049h\033[2J\033[H\033[?25l")
        sys.stdout.flush()
        yield
    finally:
        sys.stdout.write("\033[?25h\033[?1049l")
        sys.stdout.flush()
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, settings)


def main():
    parser = parser_for(__doc__)
    parser.add_argument("--confidence-threshold", type=confidence_threshold,
                        default=DEFAULT_CONFIDENCE_THRESHOLD,
                        help="minimum confidence, 0..1 (default: 0.90)")
    parser.add_argument("--max-devices", type=int, default=64)
    args = parser.parse_args()
    if args.max_devices < 1:
        parser.error("--max-devices must be positive")
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        parser.error("the dashboard requires an interactive terminal")
    worker = InferenceWorker(confidence_threshold=args.confidence_threshold)
    client = live_client(parser, args, None, "gesture-demo")
    dashboard = GestureDashboard(client, worker, args.model_id, args.require_crc, args.max_devices)
    client.on_connect, client.on_disconnect = dashboard.on_connect, dashboard.on_disconnect
    client.on_message = dashboard.on_message
    try:
        worker.start()
        with terminal_screen(), dashboard.capture_logs():
            client.loop_start()
            while True:
                worker.raise_if_failed()
                key = sys.stdin.read(1) if select.select([sys.stdin], [], [], 0)[0] else None
                if not dashboard.handle_key(key):
                    break
                size = shutil.get_terminal_size()
                sys.stdout.write(dashboard.render(size.columns, size.lines))
                sys.stdout.flush()
                worker.failed.wait(0.1)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            worker.close()
        finally:
            client.disconnect()
            client.loop_stop()


if __name__ == "__main__":
    main()
