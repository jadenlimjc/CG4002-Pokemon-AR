import sys
import time
import struct
import statistics
import paho.mqtt.client as mqtt

class TelemetryBenchmark:
    def __init__(self):
        self.packet_count = 0
        self.ping_sent_time = 0
        self.clock_offset = None
        self.latencies = []

        self.first_packet_time = None
        self.is_first_print = True

    def on_message(self, client, userdata, msg):
        now_ms = time.time() * 1000  # Ultra96 time in milliseconds

        # -----------------------------------------------------
        # Clock Synchronization
        # -----------------------------------------------------
        if msg.topic == "esp32/pong":
            esp32_millis = struct.unpack("<I", msg.payload)[0]

            rtt = now_ms - self.ping_sent_time
            one_way_delay = rtt / 2
            ultra96_time_at_publish = now_ms - one_way_delay
            self.clock_offset = ultra96_time_at_publish - esp32_millis

            print(f"Clocks synced. Offset: {self.clock_offset:.2f} ms (RTT: {rtt:.2f} ms)")
            return

        # -----------------------------------------------------
        # Telemetry Benchmarking
        # -----------------------------------------------------
        if msg.topic == "esp32/telemetry" and self.clock_offset is not None:
            if self.packet_count == 0:
                self.first_packet_time = now_ms

            esp_timestamp = struct.unpack_from("<I", msg.payload, offset=4)[0]
            esp_time_in_u96_frame = esp_timestamp + self.clock_offset
            absolute_latency = now_ms - esp_time_in_u96_frame
            self.latencies.append(absolute_latency)

            self.packet_count += 1

    def start_sync(self, client):
        print("Initiating clock sync...")
        self.ping_sent_time = time.time() * 1000
        client.publish("esp32/ping", "sync")

    def print_live_stats(self):
        if not self.latencies or self.first_packet_time is None:
            return

        avg_lat = statistics.mean(self.latencies)
        max_lat = max(self.latencies)
        min_lat = min(self.latencies)

        # Calculate real-time throughput
        elapsed_sec = (time.time() * 1000 - self.first_packet_time) / 1000.0
        hz = (self.packet_count / elapsed_sec) if elapsed_sec > 0 else 0

        # Format the dashboard layout
        lines = [
            "="*40,
            "LIVE NETWORK LATENCY STATS",
            "="*40,
            f"Total Packets   : {self.packet_count} ( {hz:.1f} Hz )",
            "-" * 40,
            f"Average Latency : {avg_lat:.2f} ms",
            f"Minimum Latency : {min_lat:.2f} ms",
            f"Maximum Spike   : {max_lat:.2f} ms",
            "="*40
        ]

        # If we've printed before, move the cursor UP by the number of lines
        if not self.is_first_print:
            sys.stdout.write(f"\033[{len(lines)}A")

        self.is_first_print = False

        # Print each line and use \033[K to clear to the end of the line
        for line in lines:
            sys.stdout.write(f"{line}\033[K\n")

        sys.stdout.flush()

if __name__ == "__main__":
    benchmark = TelemetryBenchmark()

    client = mqtt.Client()
    client.on_message = benchmark.on_message
    client.connect("localhost", 1883, 60)

    client.subscribe("esp32/pong")
    client.subscribe("esp32/telemetry")

    client.loop_start()
    benchmark.start_sync(client)

    try:
        while True:
            time.sleep(0.5)
            benchmark.print_live_stats()

    except KeyboardInterrupt:
        print("\n\n[!] Ctrl+C detected. Stopping benchmark.")

    finally:
        client.loop_stop()
        client.disconnect()
