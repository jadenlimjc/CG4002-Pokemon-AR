"""Route each FireBeetle's samples to its own buffer and a shared inference worker."""

import argparse
from collections import OrderedDict
from enum import Enum
import json
import logging
import os
from pathlib import Path
from queue import Empty
import re
import sys
from threading import Condition, Event, Thread
import time

from dotenv import find_dotenv, load_dotenv
import paho.mqtt.client as mqtt
import numpy as np

from process_telemetry import PacketError, TelemetryBuffer, decode_packet, model_input
from visualiser_protocol import GestureSequence

load_dotenv(find_dotenv())

BROKER_HOST = "127.0.0.1"
BROKER_PORT = 1883
USERNAME = os.getenv("MQTT_USER", "team_user")
PASSWORD = os.getenv("MQTT_PASSWORD")
TELEMETRY_SUBSCRIPTION = "esp32/+/telemetry"
HEALTH_SUBSCRIPTION = "esp32/+/health"
HEALTH_COUNTERS = ("boot_id", "report_index", "queue_drops", "enqueue_failures",
                   "publish_failures", "disconnected_discards", "published_samples",
                   "queue_depth", "max_publish_age_ms")


def decode_health(payload):
    """Boot-lifetime counters and maxima, never receiver delivery guarantees.

    Queue drops count overflow evictions. Enqueue failures count unsuccessful
    retries. Disconnected discards count samples dequeued without a connection.
    Explicit demo-mode queue resets are excluded. Max age includes sensor queue
    time; max duration measures the blocking telemetry publish call. Neither is
    one-way latency. Missing health reports cannot be recovered by this service.
    """
    if len(payload) > 512:
        raise ValueError("oversized health report")
    report = json.loads(payload)
    if not isinstance(report, dict):
        raise ValueError("expected health object")
    for key in HEALTH_COUNTERS:
        if type(report.get(key)) is not int or not 0 <= report[key] <= 0xffffffff:
            raise ValueError(f"invalid {key}")
    duration = report.get("max_publish_duration_us")
    if type(duration) is not int or not 0 <= duration <= 0xffffffffffffffff:
        raise ValueError("invalid max_publish_duration_us")
    if report["queue_depth"] > 20:
        raise ValueError("invalid queue depth")
    return {key: report[key] for key in (*HEALTH_COUNTERS, "max_publish_duration_us")}


def validate_model_id(value):
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", value):
        raise ValueError("model_id must contain 1-64 letters, digits, underscores or hyphens")
    return value


def device_topics(model_id):
    validate_model_id(model_id)
    topics = {name: f"esp32/{model_id}/{suffix}" for name, suffix in (
        ("telemetry", "telemetry"), ("status", "status"), ("ack", "telemetry_ack"),
        ("rtt", "rtt"), ("health", "health"), ("config", "config"), ("haptic", "haptic/cmd"),
    )}
    topics["inference"] = f"ultra96/{model_id}/inference"
    return topics


class Action(str, Enum):
    # Declaration order matches training labels and FPGA logits (indices 0-10).
    NEUTRAL = "NEUTRAL"
    AIM = "AIM"
    STOP_AIMING = "STOP_AIMING"
    THROW = "THROW"
    PUNCH = "PUNCH"
    DOWNWARD_SWIPE = "DOWNWARD_SWIPE"
    GUARD = "GUARD"
    FLEE = "FLEE"
    SWITCH_POKEMON = "SWITCH_POKEMON"
    USE_ITEM = "USE_ITEM"
    UPPERCUT = "UPPERCUT"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def create_accelerator():
    # Import only when starting inference, so packet-only tools need no PYNQ.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from fpga.cnn_pynq_ultra96 import GestureCNNAccelerator
    return GestureCNNAccelerator()


class InferenceWorker:
    """One accelerator owner; one pending complete window per device.

    A device replaces its own stale pending window without moving ahead of
    other waiting devices. The condition protects scheduling only, never DMA
    or inference. MQTT callbacks therefore remain independent of inference.
    """
    def __init__(self, accelerator_factory=None, confidence_threshold=0.75):
        if not 0 <= confidence_threshold <= 1:
            raise ValueError("confidence_threshold must be between 0 and 1")
        self.accelerator_factory = accelerator_factory or create_accelerator
        self.confidence_threshold = confidence_threshold
        self.accelerator = None
        self.ready = Event()
        self.failed = Event()
        self.failure = None
        self.condition = Condition()
        self.pending = OrderedDict()
        self.stopping = False
        self.thread = Thread(target=self._run, name="inference", daemon=True)

    def start(self):
        self.thread.start()
        # Load/program once, on the same thread that owns all inference and DMA.
        self.ready.wait()
        self.raise_if_failed()

    def raise_if_failed(self):
        if self.failure is not None:
            raise RuntimeError(f"Inference worker failed: {self.failure}") from self.failure

    def submit(self, processor, window):
        with self.condition:
            if self.stopping:
                processor.skipped_windows += 1
                return
            if processor.model_id in self.pending:
                processor.skipped_windows += 1
            self.pending[processor.model_id] = (processor, window)
            self.condition.notify()

    def _run(self):
        try:
            self.accelerator = self.accelerator_factory()
            self.ready.set()
            while True:
                with self.condition:
                    self.condition.wait_for(lambda: self.stopping or self.pending)
                    if self.stopping:
                        return
                    _, (processor, window) = self.pending.popitem(last=False)
                processor.run_inference(window)
        except Exception as error:
            self.failure = error
            self.failed.set()
            logging.exception("FPGA inference stopped")
        finally:
            self.ready.set()
            with self.condition:
                self.stopping = True
                for processor, _ in self.pending.values():
                    processor.skipped_windows += 1
                self.pending.clear()
            # Never free DMA buffers on the MQTT/UI thread while a transfer runs.
            if self.accelerator is not None:
                try:
                    self.accelerator.close()
                except Exception as error:
                    self.failure = error
                    self.failed.set()
                    logging.exception("FPGA cleanup failed")

    def close(self):
        with self.condition:
            self.stopping = True
            for processor, _ in self.pending.values():
                processor.skipped_windows += 1
            self.pending.clear()
            self.condition.notify_all()
        if self.thread.ident is not None:
            # Existing driver bounds send, execution and receive at 10 s each.
            self.thread.join(timeout=35)
            if self.thread.is_alive():
                raise RuntimeError("Inference has not stopped; accelerator still owns its buffers")


class TelemetryProcessor:
    def __init__(self, client, model_id, worker, window_size=256, hop_size=25):
        self.client = client
        self.model_id = validate_model_id(model_id)
        self.topics = device_topics(model_id)
        self.worker = worker
        self.gesture_sequence = GestureSequence()
        self.skipped_windows = 0
        self.ack_errors = 0
        self.health_report = None
        self.buffer = TelemetryBuffer(window_size=window_size, hop_size=hop_size)

    def process_packet(self, payload: bytes, received_at=None):
        # Paho supplies the entire MQTT message, even if TCP fragmented it.
        # Only the MQTT thread touches this device's buffer and sequence state.
        self.buffer.add_packet(payload, received_at=received_at)
        while True:
            try:
                window = self.buffer.output_queue.get_nowait()
            except Empty:
                break
            self.worker.submit(self, window)

    def run_inference(self, window):
        """Classify one window and retain the visualizer's per-device sequencing."""
        started = time.monotonic()
        inputs = model_input(window.features)
        logits, fpga_timing = self.worker.accelerator.predict_logits_timed(inputs)
        logits = np.asarray(logits, dtype=np.float64)
        if logits.shape != (len(Action),) or not np.isfinite(logits).all():
            raise ValueError("FPGA must return eleven finite logits in training class order")
        probabilities = np.exp(logits - logits.max())
        probabilities /= probabilities.sum()
        index = int(np.argmax(probabilities))
        predicted_action = list(Action)[index].value
        confidence = float(probabilities[index])
        completed = time.monotonic()
        timestamp_ms = time.time_ns() // 1_000_000
        timing = {key.removesuffix("_s"): value * 1000
                  for key, value in fpga_timing.as_dict().items()}
        timing["inference"] = (completed - started) * 1000
        timing["queue"] = None if window.queued_at is None else (started - window.queued_at) * 1000
        timing["receive_to_result"] = None if window.received_at is None else (completed - window.received_at) * 1000
        event = None
        status = "LOW_CONFIDENCE"
        if confidence >= self.worker.confidence_threshold:
            event = self.gesture_sequence.consume(predicted_action, confidence,
                                                  timestamp_ms=timestamp_ms)
            status = "SUPPRESSED" if event is None else "DETECTED"
        result = {
            "model_id": self.model_id,
            "predicted_action": predicted_action,
            "confidence": confidence,
            "inference_source": "fpga",
            "window_shape": list(window.features.shape),
            "model_input_shape": [6, 256],
            "sample_sequence": window.last_sequence,
            "sample_timestamp_ms": window.timestamp_ms,
            "skipped_windows": self.skipped_windows,
            "timestamp_ms": timestamp_ms,
            "timing_ms": timing,
        }
        if event is not None:
            event.update(result)
            info = self.client.publish(self.topics["inference"], json.dumps(event), qos=0, retain=False)
            status = "PUBLISHED" if info.rc == 0 else "PUBLISH_FAILED"
            if info.rc != 0:
                logging.error("[%s] Gesture publish failed: %s", self.model_id, info.rc)
        result.update(action=predicted_action, status=status,
                      published_action=None if event is None else event["action"])
        logging.info("[%s] %s %.1f%% %s | inference=%.2f ms queue=%s ms skipped=%s",
                     self.model_id, predicted_action, confidence * 100, status,
                     timing["inference"], timing["queue"], self.skipped_windows)
        # Every prediction is available to the diagnostic UI, even when gameplay
        # suppresses neutral, low-confidence or repeated/out-of-order gestures.
        return result

    def trigger_haptic(self, cmd="1"):
        self.client.publish(self.topics["haptic"], cmd)
        logging.info("[%s] Haptic command '%s' sent", self.model_id, cmd)

    def send_config(self, config_dict=None):
        if config_dict is None:
            config_dict = {"sample_rate_hz": 100, "imu_range": "8g", "debug": True}
        self.client.publish(self.topics["config"], json.dumps(config_dict))
        logging.info("[%s] Config sent", self.model_id)


class TelemetryService:
    """Discover devices from topics, with bounded state and no shared sample buffer."""
    def __init__(self, client, worker, max_devices=64, processor_factory=TelemetryProcessor):
        if max_devices < 1:
            raise ValueError("max_devices must be positive")
        self.client = client
        self.worker = worker
        self.max_devices = max_devices
        self.processor_factory = processor_factory
        self.processors = {}

    def on_message(self, client, userdata, msg):
        received_at = time.monotonic()
        parts = msg.topic.split("/")
        if (msg.retain or len(parts) != 3 or parts[0] != "esp32"
                or parts[2] not in ("telemetry", "health")):
            return
        try:
            model_id = validate_model_id(parts[1])
        except ValueError:
            return
        if parts[2] == "health":
            processor = self.processors.get(model_id)
            if processor is None:
                return # Diagnostics alone must not invent a live sample source.
            try:
                report = decode_health(msg.payload)
            except (ValueError, UnicodeError):
                logging.warning("[%s] Ignoring invalid firmware health report", model_id)
                return
            previous = processor.health_report
            if previous and report["boot_id"] == previous["boot_id"]:
                delta = (report["report_index"] - previous["report_index"]) & 0xffffffff
                if not 0 < delta < 0x80000000:
                    return
            processor.health_report = report
            logging.info("[%s] Firmware health (boot-lifetime): %s; receiver_gap_slots=%s; ack_errors=%s",
                         model_id, json.dumps(report, sort_keys=True),
                         processor.buffer.sequence_stats.gap_slots, processor.ack_errors)
            return
        try:
            packet = decode_packet(msg.payload)
        except PacketError:
            return
        if model_id not in self.processors:
            if len(self.processors) >= self.max_devices:
                logging.warning("Device limit reached; ignoring %s", model_id)
                return
            self.processors[model_id] = self.processor_factory(client, model_id, self.worker)
            logging.info("Discovered FireBeetle %s", model_id)
        processor = self.processors[model_id]
        # ACK before window processing/inference, only for CRC-verified probes.
        # The normal service supplies the responder previously present only in
        # comms_demo.py. Run one of those services at a time to avoid double ACKs.
        if packet.checked and packet.features[-1] & 0x80:
            ack = msg.payload[:8] + msg.payload[-4:]
            if client.publish(processor.topics["ack"], ack, qos=0, retain=False).rc != 0:
                processor.ack_errors += 1
        processor.process_packet(msg.payload, received_at=received_at)


def create_mqtt_client(client_id="ultra96_core"):
    client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                         client_id=client_id)
    if USERNAME and PASSWORD:
        client.username_pw_set(USERNAME, PASSWORD)
    return client


def connect_with_retry(client, host=BROKER_HOST, port=BROKER_PORT, retry_interval=2):
    client.reconnect_delay_set(min_delay=1, max_delay=30)
    while True:
        try:
            logging.info("Connecting to MQTT broker at %s:%s...", host, port)
            client.connect(host, port, keepalive=60)
            logging.info("Connected successfully to broker.")
            break
        except OSError as error:
            logging.warning("Broker connection failed (%s). Retrying in %ss...",
                            error, retry_interval)
            time.sleep(retry_interval)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-devices", type=int, default=64,
                        help="maximum distinct device buffers per run (default: 64)")
    args = parser.parse_args()
    if args.max_devices < 1:
        parser.error("--max-devices must be positive")
    if not PASSWORD:
        logging.critical("MQTT_PASSWORD environment variable is not set.")
        sys.exit(1)

    client = create_mqtt_client()
    worker = InferenceWorker()
    service = TelemetryService(client, worker, args.max_devices)

    def on_connect(cli, userdata, flags, reason_code, properties=None):
        if reason_code == 0:
            logging.info("Connected to MQTT broker.")
            cli.subscribe([(TELEMETRY_SUBSCRIPTION, 0), (HEALTH_SUBSCRIPTION, 0)])
        else:
            logging.error("Connection failed: %s", reason_code)

    client.on_connect = on_connect
    client.on_message = service.on_message
    try:
        worker.start()
        connect_with_retry(client)
        client.loop_start()
        worker.failed.wait()
        worker.raise_if_failed()
    except KeyboardInterrupt:
        logging.info("Shutting down core service...")
    finally:
        worker.close()
        client.disconnect()
        client.loop_stop()


if __name__ == "__main__":
    main()
