"""Route each FireBeetle's samples to its own buffer and a shared inference worker."""

import argparse
from collections import OrderedDict
from enum import Enum
import json
import logging
import os
from queue import Empty
import random
import re
import sys
from threading import Condition, Thread
import time

from dotenv import find_dotenv, load_dotenv
import paho.mqtt.client as mqtt

from process_telemetry import TelemetryBuffer

load_dotenv(find_dotenv())

BROKER_HOST = "127.0.0.1"
BROKER_PORT = 1883
USERNAME = os.getenv("MQTT_USER", "team_user")
PASSWORD = os.getenv("MQTT_PASSWORD")
TELEMETRY_SUBSCRIPTION = "esp32/+/telemetry"


def validate_model_id(value):
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", value):
        raise ValueError("model_id must contain 1-64 letters, digits, underscores or hyphens")
    return value


def device_topics(model_id):
    validate_model_id(model_id)
    topics = {name: f"esp32/{model_id}/{suffix}" for name, suffix in (
        ("telemetry", "telemetry"), ("status", "status"), ("ping", "ping"),
        ("pong", "pong"), ("config", "config"), ("haptic", "haptic/cmd"),
    )}
    topics["inference"] = f"ultra96/{model_id}/inference"
    return topics


class Action(str, Enum):
    AIM = "AIM"
    STOP_AIMING = "STOP_AIMING"
    THROW = "THROW"
    PUNCH = "PUNCH"
    KARATE_CHOP = "KARATE_CHOP"
    GUARD = "GUARD"


logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


class InferenceWorker:
    """One accelerator owner; one pending complete window per device.

    A device replaces its own stale pending window without moving ahead of
    other waiting devices. The condition protects scheduling only, never DMA
    or inference. MQTT callbacks therefore remain independent of inference.
    """
    def __init__(self):
        self.condition = Condition()
        self.pending = OrderedDict()
        self.stopping = False
        self.thread = Thread(target=self._run, name="inference", daemon=True)

    def start(self):
        self.thread.start()

    def submit(self, processor, window):
        with self.condition:
            if self.stopping:
                return
            if processor.model_id in self.pending:
                processor.skipped_windows += 1
            self.pending[processor.model_id] = (processor, window)
            self.condition.notify()

    def _run(self):
        while True:
            with self.condition:
                self.condition.wait_for(lambda: self.stopping or self.pending)
                if self.stopping:
                    return
                _, (processor, window) = self.pending.popitem(last=False)
            try:
                processor.run_inference(window)
            except Exception:
                logging.exception("[%s] Inference failed", processor.model_id)

    def close(self):
        with self.condition:
            self.stopping = True
            for processor, _ in self.pending.values():
                processor.skipped_windows += 1
            self.pending.clear()
            self.condition.notify_all()
        if self.thread.ident is not None:
            self.thread.join(timeout=5)
            if self.thread.is_alive():
                logging.warning("Inference is still finishing during shutdown")


class TelemetryProcessor:
    def __init__(self, client, model_id, worker, window_size=20, hop_size=10):
        self.client = client
        self.model_id = validate_model_id(model_id)
        self.topics = device_topics(model_id)
        self.worker = worker
        self.skipped_windows = 0
        self.buffer = TelemetryBuffer(window_size=window_size, hop_size=hop_size)

    def process_packet(self, payload: bytes):
        # Paho supplies the entire MQTT message, even if TCP fragmented it.
        # Only the MQTT thread touches this device's buffer and sequence state.
        self.buffer.add_packet(payload)
        while True:
            try:
                window = self.buffer.output_queue.get_nowait()
            except Empty:
                break
            self.worker.submit(self, window)

    def run_inference(self, window):
        """Placeholder inference; the shared worker will own the future FPGA DMA."""
        predicted_action = random.choice(list(Action))
        confidence = round(random.uniform(0.85, 0.99), 2)
        result_payload = {
            "model_id": self.model_id,
            "action": predicted_action.value,
            "confidence": confidence,
            "window_shape": list(window.features.shape),
            "sample_sequence": window.last_sequence,
            "sample_timestamp_ms": window.timestamp_ms,
            "skipped_windows": self.skipped_windows,
            "timestamp_ms": int(time.time() * 1000),
        }
        self.client.publish(self.topics["inference"], json.dumps(result_payload))
        logging.info("[%s] Window %s -> %s (%.0f%%)", self.model_id,
                     window.features.shape, predicted_action.value, confidence * 100)

    def trigger_haptic(self, cmd="1"):
        self.client.publish(self.topics["haptic"], cmd)
        logging.info("[%s] Haptic command '%s' sent", self.model_id, cmd)

    def send_config(self, config_dict=None):
        if config_dict is None:
            config_dict = {"sample_rate_hz": 50, "imu_range": "8g", "debug": True}
        self.client.publish(self.topics["config"], json.dumps(config_dict))
        logging.info("[%s] Config sent", self.model_id)


class TelemetryService:
    """Discover devices from topics, with bounded state and no shared sample buffer."""
    def __init__(self, client, worker, max_devices=64):
        if max_devices < 1:
            raise ValueError("max_devices must be positive")
        self.client = client
        self.worker = worker
        self.max_devices = max_devices
        self.processors = {}

    def on_message(self, client, userdata, msg):
        parts = msg.topic.split("/")
        if msg.retain or len(parts) != 3 or parts[0] != "esp32" or parts[2] != "telemetry":
            return
        try:
            model_id = validate_model_id(parts[1])
        except ValueError:
            return
        if model_id not in self.processors:
            if len(self.processors) >= self.max_devices:
                logging.warning("Device limit reached; ignoring %s", model_id)
                return
            self.processors[model_id] = TelemetryProcessor(client, model_id, self.worker)
            logging.info("Discovered FireBeetle %s", model_id)
        self.processors[model_id].process_packet(msg.payload)


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
            cli.subscribe(TELEMETRY_SUBSCRIPTION)
        else:
            logging.error("Connection failed: %s", reason_code)

    client.on_connect = on_connect
    client.on_message = service.on_message
    try:
        connect_with_retry(client)
        worker.start()
        client.loop_forever()
    except KeyboardInterrupt:
        logging.info("Shutting down core service...")
    finally:
        worker.close()
        client.disconnect()


if __name__ == "__main__":
    main()
