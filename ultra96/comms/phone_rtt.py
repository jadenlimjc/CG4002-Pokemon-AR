"""Run on Ultra96 to echo phone RTT probes over the existing MQTT connection.

Run exactly one responder. The latency collector already includes this echo.
"""
import argparse
import logging
import os
import re
from uuid import uuid4

REQUEST_TOPIC = "phone/+/rtt/request"
PAYLOAD_SIZE = 32


def echo_response(topic, payload, retained=False):
    """Return a validated probe's reply topic and unchanged payload."""
    parts = topic.split("/")
    if (retained or len(parts) != 4 or parts[0] != "phone"
            or parts[2:] != ["rtt", "request"]
            or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", parts[1])
            or len(payload) != PAYLOAD_SIZE or payload[:4] != b"PRT1"):
        return None
    return f"phone/{parts[1]}/rtt/reply", bytes(payload)


def main():
    from dotenv import find_dotenv, load_dotenv
    import paho.mqtt.client as mqtt
    load_dotenv(find_dotenv())
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=1883)
    args = parser.parse_args()
    password = os.getenv("MQTT_PASSWORD")
    if not password:
        parser.error("Set MQTT_PASSWORD in the environment or project .env")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                         client_id="phone-rtt-" + uuid4().hex[:12])
    client.username_pw_set(os.getenv("MQTT_USER", "team_user"), password)
    client.reconnect_delay_set(min_delay=1, max_delay=10)

    def on_connect(cli, userdata, flags, reason, properties):
        if reason == 0:
            cli.subscribe(REQUEST_TOPIC, qos=0)
        else:
            logging.error("Broker connection rejected: %s", reason)

    def on_subscribe(cli, userdata, mid, reasons, properties):
        if any(reason.is_failure for reason in reasons):
            logging.error("Broker rejected phone RTT subscription")
        else:
            logging.info("Phone RTT responder ready on %s:%s", args.host, args.port)

    def on_message(cli, userdata, message):
        response = echo_response(message.topic, message.payload, message.retain)
        if response:
            result = cli.publish(response[0], response[1], qos=0, retain=False)
            if result.rc != mqtt.MQTT_ERR_SUCCESS:
                logging.warning("Phone RTT reply publish failed: %s", result.rc)

    client.on_connect = on_connect
    client.on_subscribe = on_subscribe
    client.on_message = on_message
    client.connect_async(args.host, args.port, keepalive=30)
    try:
        client.loop_forever(retry_first_connection=True)
    except KeyboardInterrupt:
        pass
    finally:
        client.disconnect()


if __name__ == "__main__":
    main()
