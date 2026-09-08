import json
import logging
import os
import sys
import random
import time
import socket
from enum import Enum
from dotenv import find_dotenv, load_dotenv
import paho.mqtt.client as mqtt

from process_telemetry import TelemetryBuffer

load_dotenv(find_dotenv())

BROKER_HOST = "127.0.0.1"
BROKER_PORT = 1883
USERNAME = os.getenv("MQTT_USER", "team_user")
PASSWORD = os.getenv("MQTT_PASSWORD")

TOPIC_SENSOR_RAW = "esp32/telemetry"
TOPIC_INFERENCE_RESULT = "ultra96/inference"
TOPIC_HAPTIC = "esp32/haptic/cmd"
TOPIC_CONFIG = "esp32/config"


class Action(str, Enum):
    AIM = "AIM"
    STOP_AIMING = "STOP_AIMING"
    THROW = "THROW"
    PUNCH = "PUNCH"
    KARATE_CHOP = "KARATE_CHOP"
    GUARD = "GUARD"


logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)


class TelemetryProcessor:
    def __init__(self, client: mqtt.Client, window_size=20, hop_size=10):
        self.client = client
        self.buffer = TelemetryBuffer(window_size=window_size, hop_size=hop_size)

    def process_packet(self, payload: bytes):
        self.buffer.add_packet(payload)

        while not self.buffer.output_queue.empty():
            window_matrix = self.buffer.output_queue.get_nowait()
            self.run_inference(window_matrix)

    def run_inference(self, feature_matrix):
        """Simulates model inference and triggers downstream haptics."""
        predicted_action = random.choice(list(Action))
        confidence = round(random.uniform(0.85, 0.99), 2)

        result_payload = {
            "action": predicted_action.value,
            "confidence": confidence,
            "window_shape": list(feature_matrix.shape),
            "timestamp_ms": int(time.time() * 1000),
        }

        self.client.publish(TOPIC_INFERENCE_RESULT, json.dumps(result_payload))
        logging.info(
            f"[Inference] Window {feature_matrix.shape} -> {predicted_action.value} ({confidence * 100:.0f}%)"
        )

        if predicted_action in [Action.PUNCH, Action.KARATE_CHOP, Action.THROW]:
            self.trigger_haptic("1")

    def trigger_haptic(self, cmd="1"):
        self.client.publish(TOPIC_HAPTIC, cmd)
        logging.info(f"[Haptic] Command '{cmd}' sent.")

    def send_config(self, config_dict=None):
        if config_dict is None:
            config_dict = {"sample_rate_hz": 50, "imu_range": "8g", "debug": True}
        self.client.publish(TOPIC_CONFIG, json.dumps(config_dict))
        logging.info(f"[Config] Updated config sent to {TOPIC_CONFIG}")


def create_mqtt_client():
    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id="ultra96_core",
    )
    if USERNAME and PASSWORD:
        client.username_pw_set(USERNAME, PASSWORD)
    return client


def connect_with_retry(client, host=BROKER_HOST, port=BROKER_PORT, retry_interval=2):
    client.reconnect_delay_set(min_delay=1, max_delay=30)
    while True:
        try:
            logging.info(f"Connecting to MQTT broker at {host}:{port}...")
            client.connect(host, port, keepalive=60)
            logging.info("Connected successfully to broker.")
            break
        except (socket.error, OSError, Exception) as e:
            logging.warning(f"Broker connection failed ({e}). Retrying in {retry_interval}s...")
            time.sleep(retry_interval)


def main():
    if not PASSWORD:
        logging.critical("MQTT_PASSWORD environment variable is not set.")
        sys.exit(1)

    client = create_mqtt_client()
    processor = TelemetryProcessor(client)

    def on_connect(cli, userdata, flags, reason_code, properties=None):
        if reason_code == 0:
            logging.info("Connected to MQTT broker.")
            cli.subscribe(TOPIC_SENSOR_RAW)
        else:
            logging.error(f"Connection failed: {reason_code}")

    def on_message(cli, userdata, msg):
        if msg.topic == TOPIC_SENSOR_RAW:
            processor.process_packet(msg.payload)

    client.on_connect = on_connect
    client.on_message = on_message

    connect_with_retry(client)

    try:
        client.loop_forever()
    except KeyboardInterrupt:
        logging.info("Shutting down core service...")
        client.disconnect()


if __name__ == "__main__":
    main()
