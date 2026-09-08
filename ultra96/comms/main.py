import json
import logging
import os
import sys
from dotenv import find_dotenv, load_dotenv
import paho.mqtt.client as mqtt

load_dotenv(find_dotenv())

BROKER_HOST = "127.0.0.1"
BROKER_PORT = 1883
USERNAME = os.getenv("MQTT_USER", "team_user")
PASSWORD = os.getenv("MQTT_PASSWORD")

TOPIC_SENSOR_RAW = "esp32/telemetry"
TOPIC_INFERENCE_RESULT = "ultra96/inference"
TOPIC_CONFIG = "esp32/config"
TOPIC_HAPTIC = "esp32/haptic/cmd"

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)


def on_connect(client, userdata, flags, reason_code, properties=None):
    if reason_code == 0:
        logging.info(f"Connected to broker at {BROKER_HOST}:{BROKER_PORT}")
        client.subscribe(TOPIC_SENSOR_RAW)
        logging.info(f"Subscribed to topic: {TOPIC_SENSOR_RAW}")
    else:
        logging.error(f"Connection failed with reason code: {reason_code}")


def on_disconnect(client, userdata, flags, reason_code, properties=None):
    if reason_code != 0:
        logging.warning(
            f"Unexpected disconnection (code: {reason_code}). Reconnecting..."
        )
    else:
        logging.info("Disconnected from broker successfully.")


def on_message(client, userdata, msg):
    try:
        # currently add_packet is not throwing an error
        telemetry_buf.add_packet(msg.payload)
    except Exception as e:
        logging.error(f"Error handling binary packet on {msg.topic}: {e}")


def main():
    if not PASSWORD:
        logging.critical("MQTT_PASSWORD environment variable is not set.")
        sys.exit(1)

    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id="ultra96",
    )
    client.username_pw_set(USERNAME, PASSWORD)

    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message

    client.reconnect_delay_set(min_delay=1, max_delay=120)

    logging.info(f"Connecting to broker at {BROKER_HOST}:{BROKER_PORT}...")
    try:
        client.connect(BROKER_HOST, BROKER_PORT, keepalive=60)
        client.loop_forever()
    except KeyboardInterrupt:
        logging.info("Shutting down listener cleanly...")
        client.disconnect()
    except Exception as e:
        logging.critical(f"Fatal broker connection error: {e}")


if __name__ == "__main__":
    main()
