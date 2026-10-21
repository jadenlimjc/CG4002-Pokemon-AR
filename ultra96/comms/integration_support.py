"""Shared runtime support for the live packet viewer and processing demo.

These helpers are required by the tools in tests/; they are not test fixtures.
"""

import argparse
import logging
from uuid import uuid4

import main as comms


def parser_for(description):
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--host", default=comms.BROKER_HOST)
    parser.add_argument("--port", type=int, default=comms.BROKER_PORT)
    parser.add_argument("--model-id", type=comms.validate_model_id,
                        help="only receive this board (default: all boards)")
    parser.add_argument("--require-crc", action="store_true",
                        help="reject legacy packets without a CRC")
    return parser


def telemetry_device(message, model_id=None):
    """Return the selected device ID for live, well-formed telemetry topics."""
    parts = message.topic.split("/")
    if (message.retain or len(parts) != 3 or parts[0] != "esp32"
            or parts[2] != "telemetry"):
        return None
    try:
        device = comms.validate_model_id(parts[1])
    except ValueError:
        return None
    return device if model_id is None or device == model_id else None


def live_client(parser, args, on_message, client_id):
    """Configure a client; the caller starts and stops its network loop."""
    if not comms.PASSWORD:
        parser.error("Set MQTT_PASSWORD in the environment or project .env")
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    client = comms.create_mqtt_client(client_id + "-" + uuid4().hex[:12])
    topic = (f"esp32/{args.model_id}/telemetry" if args.model_id
             else comms.TELEMETRY_SUBSCRIPTION)

    def on_connect(cli, userdata, flags, reason_code, properties=None):
        if reason_code == 0:
            cli.subscribe(topic, qos=0)
        else:
            logging.error("Broker connection rejected: %s", reason_code)

    client.on_connect = on_connect
    client.on_message = on_message
    client.reconnect_delay_set(min_delay=1, max_delay=30)
    client.connect_async(args.host, args.port, keepalive=60)
    return client
