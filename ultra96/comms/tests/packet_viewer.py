"""Print every live ESP32 packet on Ultra96, with no inference or metrics."""

import logging

from integration_support import live_client, parser_for, telemetry_device
from process_telemetry import BODY, CRC, PacketError, decode_packet


def packet_line(model_id, payload, require_crc=False):
    packet = decode_packet(payload, require_crc=require_crc)
    ax, ay, az, gx, gy, gz, touch, flags = packet.features
    crc = f"0x{CRC.unpack_from(payload, BODY.size)[0]:08x} (valid)" if packet.checked else "absent (legacy)"
    return (
        f"[{model_id}] sample_index={packet.sequence} timestamp_ms={packet.timestamp_ms} "
        f"accel_x={ax} accel_y={ay} accel_z={az} "
        f"gyro_x={gx} gyro_y={gy} gyro_z={gz} "
        f"touch_mask=0x{touch:04x} flags=0x{flags:02x} crc32={crc}"
    )


class PacketViewer:
    def __init__(self, model_id=None, require_crc=False, output=print):
        self.model_id, self.require_crc, self.output = model_id, require_crc, output

    def on_message(self, client, userdata, message):
        model_id = telemetry_device(message, self.model_id)
        if model_id is None:
            return
        try:
            line = packet_line(model_id, message.payload, self.require_crc)
        except PacketError as error:
            logging.warning("[%s] Rejected packet: %s", model_id, error)
            return
        self.output(line, flush=True)


def main():
    parser = parser_for(__doc__)
    args = parser.parse_args()
    viewer = PacketViewer(args.model_id, args.require_crc)
    client = live_client(parser, args, viewer.on_message, "packet-viewer")
    try:
        client.loop_forever(retry_first_connection=True)
    except KeyboardInterrupt:
        pass
    finally:
        client.disconnect()


if __name__ == "__main__":
    main()
