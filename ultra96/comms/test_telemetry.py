import os
import sys
import time
import struct
import statistics
import json
import select
import termios
import tty
from datetime import datetime
import paho.mqtt.client as mqtt

LOG_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "logs"))
LOG_FILE = os.path.join(LOG_DIR, "telemetry_bench.csv")

TOPIC_CONFIG = "esp32/config"
TOPIC_HAPTIC = "esp32/haptic/cmd"

# Downstream test payloads
CONFIG_PAYLOAD = json.dumps({"sample_rate_hz": 50, "imu_range": "8g", "debug": True})
HAPTIC_PAYLOAD = "1"  # Minimal 1-byte payload


class TelemetryBenchmark:
    def __init__(self):
        self.packet_count = 0
        self.ping_sent_time = 0
        self.clock_offset = None
        self.latencies = []

        self.first_packet_time = None
        self.is_first_print = True
        self.last_action_msg = "Ready (Press key options below)"

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
            self.last_action_msg = f"Synced: Offset={self.clock_offset:.2f}ms"
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
        self.last_action_msg = "Initiating clock sync..."
        self.ping_sent_time = time.time() * 1000
        client.publish("esp32/ping", "sync")

    def print_live_stats(self):
        avg_lat = statistics.mean(self.latencies) if self.latencies else 0.0
        max_lat = max(self.latencies) if self.latencies else 0.0
        min_lat = min(self.latencies) if self.latencies else 0.0

        # Calculate real-time throughput
        elapsed_sec = (
            ((time.time() * 1000 - self.first_packet_time) / 1000.0)
            if self.first_packet_time
            else 0.0
        )
        hz = (self.packet_count / elapsed_sec) if elapsed_sec > 0 else 0

        # Format the dashboard layout
        lines = [
            "=" * 44,
            "     LIVE NETWORK & COMMAND DASHBOARD      ",
            "=" * 44,
            f" Total Packets   : {self.packet_count} ( {hz:.1f} Hz )",
            "-" * 44,
            f" Avg Latency     : {avg_lat:.2f} ms",
            f" Min Latency     : {min_lat:.2f} ms",
            f" Max Latency     : {max_lat:.2f} ms",
            "-" * 44,
            f" Last Action     : {self.last_action_msg}",
            "-" * 44,
            " [1 / c] Send Config JSON",
            " [2 / h] Send Haptic Command",
            " [q / ^C] Stop Benchmark",
            "=" * 44,
        ]

        # If we've printed before, move the cursor UP by the number of lines
        if not self.is_first_print:
            sys.stdout.write(f"\033[{len(lines)}A")

        self.is_first_print = False

        # Print each line and use \033[K to clear to the end of the line
        for line in lines:
            sys.stdout.write(f"{line}\033[K\n")

        sys.stdout.flush()

    def log_final_metrics(self):
        """Appends run summaries to the CSV log file upon script completion."""
        if not self.latencies or self.first_packet_time is None:
            print("[!] No latency metrics collected to log.")
            return

        os.makedirs(LOG_DIR, exist_ok=True)
        file_exists = os.path.isfile(LOG_FILE)

        avg_lat = statistics.mean(self.latencies)
        max_lat = max(self.latencies)
        min_lat = min(self.latencies)
        elapsed_sec = (time.time() * 1000 - self.first_packet_time) / 1000.0
        hz = (self.packet_count / elapsed_sec) if elapsed_sec > 0 else 0
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        offset_val = (
            f"{self.clock_offset:.2f}" if self.clock_offset is not None else "N/A"
        )

        with open(LOG_FILE, mode="a", encoding="utf-8") as f:
            if not file_exists:
                f.write(
                    "Timestamp,Total Packets,Duration (s),Throughput (Hz),Avg Latency (ms),Min Latency (ms),Max Latency (ms),Clock Offset (ms)\n"
                )

            f.write(
                f"{timestamp},{self.packet_count},{elapsed_sec:.2f},{hz:.2f},{avg_lat:.2f},{min_lat:.2f},{max_lat:.2f},{offset_val}\n"
            )

        print(f"\n[+] Summary log written to: {LOG_FILE}")


def get_key_non_blocking():
    """Checks for keyboard input without blocking execution."""
    if select.select([sys.stdin], [], [], 0) == ([sys.stdin], [], []):
        return sys.stdin.read(1)
    return None


if __name__ == "__main__":
    benchmark = TelemetryBenchmark()

    client = mqtt.Client()
    client.on_message = benchmark.on_message
    client.connect("localhost", 1883, 60)

    client.subscribe("esp32/pong")
    client.subscribe("esp32/telemetry")

    client.loop_start()
    benchmark.start_sync(client)

    # Set terminal to cbreak mode to capture single keypresses directly
    old_settings = termios.tcgetattr(sys.stdin)

    try:
        tty.setcbreak(sys.stdin.fileno())

        while True:
            key = get_key_non_blocking()

            if key in ("1", "c"):
                client.publish(TOPIC_CONFIG, CONFIG_PAYLOAD)
                benchmark.last_action_msg = f"Published -> {TOPIC_CONFIG}"
            elif key in ("2", "h"):
                client.publish(TOPIC_HAPTIC, HAPTIC_PAYLOAD)
                benchmark.last_action_msg = f"Published -> {TOPIC_HAPTIC}"
            elif key == "q":
                break

            benchmark.print_live_stats()
            time.sleep(0.1)

    except KeyboardInterrupt:
        pass

    finally:
        # Restore standard terminal settings
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)
        print("\n\n[!] Stopping benchmark.")

        client.loop_stop()
        client.disconnect()
        benchmark.log_final_metrics()
