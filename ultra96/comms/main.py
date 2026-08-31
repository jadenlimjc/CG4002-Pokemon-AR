import json
import os
import sys
from dotenv import find_dotenv, load_dotenv
import paho.mqtt.client as mqtt

load_dotenv(find_dotenv())

BROKER_HOST = os.getenv("MQTT_HOST", "127.0.0.1")
BROKER_PORT = int(os.getenv("MQTT_PORT", 1883))
USERNAME = os.getenv("MQTT_USER", "team_user")
PASSWORD = os.getenv("MQTT_PASSWORD")

TOPIC_SENSOR_RAW = "pals/sensor/raw"
TOPIC_INFERENCE_RESULT = "pals/inference/result"


def process_inference(sensor_data: dict) -> dict:
    """Placeholder for ML model processing (PyTorch / NumPy)."""
    # Extract values sent by ESP32 (e.g., ax, ay, az, gx, gy, gz)
    accel = sensor_data.get("accel", [0.0, 0.0, 0.0])

    # TODO: Pass extracted arrays into your PyTorch/Inference logic
    prediction = "IDLE"  # e.g., model.predict(accel)

    return {"status": "SUCCESS", "predicted_action": prediction, "raw_count": len(accel)}


def on_connect(client, userdata, flags, reason_code, properties=None):
    if reason_code == 0:
        print(f"[Ultra96] Connected to MQTT broker at {BROKER_HOST}:{BROKER_PORT}")
        client.subscribe(TOPIC_SENSOR_RAW)
        print(f"[Ultra96] Subscribed to topic: {TOPIC_SENSOR_RAW}")
    else:
        print(f"[Ultra96] Connection failed with reason code: {reason_code}")


def on_message(client, userdata, msg):
    try:
        raw_payload = msg.payload.decode("utf-8")
        data = json.loads(raw_payload)
        print(f"[Ultra96] Received from {msg.topic}: {data}")

        # Execute ML pipeline
        result = process_inference(data)

        # Publish predictions back out to Unity visualizer / Laptop
        client.publish(TOPIC_INFERENCE_RESULT, json.dumps(result))
        print(f"[Ultra96] Published inference to {TOPIC_INFERENCE_RESULT}: {result}")

    except json.JSONDecodeError:
        print(f"[Ultra96] Warning: Failed to parse non-JSON payload on {msg.topic}")
    except Exception as e:
        print(f"[Ultra96] Error processing payload: {e}")


def main():
    if not PASSWORD:
        print("[Ultra96] Error: MQTT_PASSWORD environment variable is not set.")
        sys.exit(1)

    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2, client_id="ultra96_worker"
    )
    client.username_pw_set(USERNAME, PASSWORD)

    client.on_connect = on_connect
    client.on_message = on_message

    print(f"[Ultra96] Connecting to broker at {BROKER_HOST}:{BROKER_PORT}...")
    try:
        client.connect(BROKER_HOST, BROKER_PORT, keepalive=60)
        client.loop_forever()
    except KeyboardInterrupt:
        print("\n[Ultra96] Shutting down listener cleanly...")
        client.disconnect()
    except Exception as e:
        print(f"[Ultra96] Failed to connect: {e}")


if __name__ == "__main__":
    main()
