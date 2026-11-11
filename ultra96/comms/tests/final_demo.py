"""Final live demo: inference, manual gameplay controls, and key link metrics.

Run this instead of main.py/comms_demo.py, so only one service sends gestures
and telemetry ACKs. Uses the production TelemetryProcessor and FPGA worker.
"""

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
from pairing import (
    PAIR_REQUEST_SUBSCRIPTION, PairingService, player_id_for_model,
)
from process_telemetry import (MENU_CONTROL_MASK, PacketError, SequenceStats,
                               decode_packet)
from telemetry_diagnostics import TelemetryHealth, TelemetryRtt
from visualiser_protocol import DEFAULT_CONFIDENCE_THRESHOLD, confidence_threshold


MANUAL_ACTIONS = {
    "1": ("SET_TUTORIAL", "TUTORIAL"),
    "t": ("SET_TUTORIAL", "TUTORIAL"),
    "2": ("SET_GOD_MODE", "GOD MODE"),
    "g": ("SET_GOD_MODE", "GOD MODE"),
    "3": ("SET_FULL_PLAY", "FULL PLAY"),
    "f": ("SET_FULL_PLAY", "FULL PLAY"),
    "4": ("SKIP_STEP", None),
    "s": ("SKIP_STEP", None),
}
SUPPORTED_MANUAL_ACTIONS = frozenset(action for action, _ in MANUAL_ACTIONS.values())


def debug_payload(payload, limit=512):
    """Render bounded MQTT payload text without letting diagnostics fail."""
    if isinstance(payload, bytes):
        text = payload.decode("utf-8", errors="backslashreplace")
    else:
        text = str(payload)
    return text if len(text) <= limit else text[:limit] + "...<truncated>"


class PairingTraceClient:
    """Log every publication made by PairingService and preserve its result."""

    def __init__(self, client):
        self.client = client
        self.publish_count = 0

    def publish(self, topic, payload, **kwargs):
        result = self.client.publish(topic, payload, **kwargs)
        self.publish_count += 1
        logging.info(
            "[PAIRING TX] topic=%s qos=%s retain=%s rc=%s payload=%s",
            topic, kwargs.get("qos", 0), kwargs.get("retain", False),
            getattr(result, "rc", "unknown"), debug_payload(payload),
        )
        return result


class GestureMonitor:
    """Per-device inference state, manual controls, and compact link metrics."""

    def __init__(self, processor, require_crc=False):
        self.processor = processor
        self.require_crc = require_crc
        self.lock = RLock()
        self.health = TelemetryHealth(time.monotonic())
        self.rtt = TelemetryRtt()
        self.sequences = SequenceStats()
        self.gameplay_mode = "FULL PLAY"
        self.last_manual_action = "-- none sent"
        self.last_menu_sequence = None

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

        if message.retain:
            return False
        try:
            packet = decode_packet(message.payload, require_crc=self.require_crc)
        except PacketError:
            return False
        self.rtt.acknowledge(self.processor.client, self.processor.topics["ack"],
                             packet, message.payload)
        menu_flags = int(packet.features[-1]) & MENU_CONTROL_MASK
        player_id = player_id_for_model(self.processor.model_id)
        if (menu_flags and player_id is not None
                and self.last_menu_sequence != packet.sequence):
            payload = json.dumps({"flags": menu_flags, "sequence": packet.sequence},
                                 separators=(",", ":"), sort_keys=True)
            info = self.processor.client.publish(
                f"ultra96/{player_id}/menu_controls", payload, qos=0, retain=False)
            if info.rc == 0:
                self.last_menu_sequence = packet.sequence
        if not self.sequences.observe(packet):
            return False
        self.health.observe(now, packet.sequence, packet.timestamp_ms)
        return True

    def publish_manual_action(self, action, gameplay_mode=None):
        if action not in SUPPORTED_MANUAL_ACTIONS:
            raise ValueError(f"Unsupported manual action: {action!r}")
        payload = {
            "action": action,
            "gesture_id": 0,
            "confidence": 1.0,
            "timestamp": 0,
        }
        info = self.processor.client.publish(
            self.processor.topics["inference"],
            json.dumps(payload, separators=(",", ":")),
            qos=0,
            retain=False,
        )
        with self.lock:
            if info.rc == 0:
                if gameplay_mode is not None:
                    self.gameplay_mode = gameplay_mode
                self.last_manual_action = f"{action} (MQTT accepted)"
                logging.info("[%s] Manual action %s sent", self.processor.model_id, action)
                return True
            self.last_manual_action = f"{action} FAILED (rc={info.rc})"
            logging.error("[%s] Manual action %s failed: %s",
                          self.processor.model_id, action, info.rc)
            return False

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
            lines += [f" CURRENT: {current['predicted_action']} | {current['confidence']:.2%} "
                      f"(threshold {current['confidence_threshold']:.2%}) | "
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
            _, _, hz = self.health.snapshot(now)
            show = lambda value: "--" if value is None else f"{value:.2f}"
            lines += [f" MODES: throw {self.processor.throw_action} | gameplay {self.gameplay_mode}",
                      " INPUT: [1/t] Tutorial | [2/g] God mode | "
                      "[3/f] Full play | [4/s] Skip step",
                      f" MANUAL SEND: {self.last_manual_action}",
                      f" Packet rate: {hz} Hz / 50 Hz expected",
                      f" RTT: {show(self.rtt.mean_ms)} ms | Est. one-way: "
                      f"{show(self.rtt.estimated_one_way_ms)} ms"]
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
        self.pairing_client = PairingTraceClient(client)
        self.pairing = PairingService(self.pairing_client)

    def on_connect(self, client, userdata, flags, reason_code, properties=None):
        self.broker_online = reason_code == 0
        if self.broker_online:
            device = self.model_id or "+"
            subscriptions = [(f"esp32/{device}/{suffix}",
                              1 if suffix == "status" else 0)
                             for suffix in ("telemetry", "status", "rtt")]
            subscriptions.append((PAIR_REQUEST_SUBSCRIPTION, 1))
            client.subscribe(subscriptions)
            logging.info("[PAIRING] subscribed to esp32/%s/status and %s",
                         device, PAIR_REQUEST_SUBSCRIPTION)
        else:
            logging.error("Broker connection rejected: %s", reason_code)

    def on_disconnect(self, client, userdata, flags, reason_code, properties=None):
        self.broker_online = False

    def on_message(self, client, userdata, message):
        now = time.monotonic()
        parts = message.topic.split("/")
        is_device_status = (len(parts) == 3 and parts[0] == "esp32"
                            and parts[2] == "status")
        is_pairing_request = (len(parts) == 4 and parts[0] == "visualiser"
                              and parts[2:] == ["pair", "request"])
        if is_device_status or is_pairing_request:
            logging.info("[PAIRING RX] topic=%s retain=%s payload=%s",
                         message.topic, message.retain,
                         debug_payload(message.payload))
            publications_before = self.pairing_client.publish_count
            handled = self.pairing.handle_message(message)
            if is_device_status and self.pairing_client.publish_count == publications_before:
                logging.warning(
                    "[PAIRING NO FORWARD] topic=%s was not mapped to a visualiser player",
                    message.topic,
                )
            if is_pairing_request:
                if not handled:
                    logging.warning("[PAIRING NO FORWARD] request was not handled: %s",
                                    message.topic)
                return
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
        elif key in MANUAL_ACTIONS and boards:
            action, gameplay_mode = MANUAL_ACTIONS[key]
            boards[self.selected].publish_manual_action(action, gameplay_mode)
        return key != "q"

    def lines(self, now=None):
        now = time.monotonic() if now is None else now
        boards = self.boards()
        broker = "connected" if self.broker_online else "DISCONNECTED"
        lines = [f" FINAL DEMO | Broker {broker} | threshold {self.worker.confidence_threshold:.2%}"]
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
        footer = " [1-4 / t,g,f,s] Manual action | [Tab] Device | [q / Ctrl-C] Quit"
        if len(lines) > max(0, height - 2):
            lines = lines[:max(0, height - 2)]
            footer = " Resize taller. [1-4] Action | [Tab] Device | [q] Quit"
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
                        help="default minimum confidence, 0..1 (default: 0.60)")
    parser.add_argument("--max-devices", type=int, default=64)
    args = parser.parse_args()
    if args.max_devices < 1:
        parser.error("--max-devices must be positive")
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        parser.error("the dashboard requires an interactive terminal")
    worker = InferenceWorker(confidence_threshold=args.confidence_threshold)
    client = live_client(parser, args, None, "final-demo")
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
