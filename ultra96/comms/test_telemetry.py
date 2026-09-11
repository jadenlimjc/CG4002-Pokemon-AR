import os
import logging
import shutil
import sys
import time
import struct
import statistics
import select
import termios
import tty
from datetime import datetime
from contextlib import contextmanager

from main import (
    TelemetryProcessor,
    create_mqtt_client,
    connect_with_retry,
    BROKER_HOST,
    BROKER_PORT,
    TOPIC_SENSOR_RAW,
)

LOG_DIR = os.path.abspath(os.path.dirname(__file__))
LOG_FILE = os.path.join(LOG_DIR, "telemetry_bench.csv")


class DashboardLogFilter(logging.Filter):
    def __init__(self, benchmark):
        super().__init__()
        self.benchmark = benchmark

    def filter(self, record):
        self.benchmark.last_log_msg = f"[{record.levelname}] {record.getMessage()}"
        # The UI thread renders logs; MQTT callbacks must not move the cursor.
        return False


class TelemetryBenchmark:
    def __init__(self, processor: TelemetryProcessor):
        self.processor = processor
        self.packet_count = 0
        self.ping_sent_time = 0
        self.clock_offset = None
        self.latencies = []

        self.first_packet_time = None
        self.is_first_print = True
        self.last_action_msg = "Ready (Press key options below)"
        self.last_log_msg = "No messages yet"

    @contextmanager
    def dashboard_logging(self):
        log_filter = DashboardLogFilter(self)
        console_handlers = [
            handler for handler in logging.getLogger().handlers
            if isinstance(handler, logging.StreamHandler)
            and not isinstance(handler, logging.FileHandler)
            and handler.stream in (sys.stdout, sys.stderr)
        ]
        for handler in console_handlers:
            handler.addFilter(log_filter)
        try:
            yield
        finally:
            for handler in console_handlers:
                handler.removeFilter(log_filter)

    def on_message(self, client, userdata, msg):
        now_ms = time.time() * 1000

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
        # Telemetry Latency Benchmarking & Main Pipeline Forwarding
        # -----------------------------------------------------
        if msg.topic == TOPIC_SENSOR_RAW:
            if self.clock_offset is not None:
                if self.packet_count == 0:
                    self.first_packet_time = now_ms

                esp_timestamp = struct.unpack_from("<I", msg.payload, offset=4)[0]
                esp_time_in_u96_frame = esp_timestamp + self.clock_offset
                absolute_latency = now_ms - esp_time_in_u96_frame
                self.latencies.append(absolute_latency)
                self.packet_count += 1

            # FORWARD PACKET DIRECTLY TO MAIN INFERENCE PIPELINE
            self.processor.process_packet(msg.payload)

    def wait_for_clock_sync(self, client, ping_interval=1.0) -> bool:
        print("[*] Waiting for ESP32 to come online for clock sync...")
        dots = 0

        while self.clock_offset is None:
            self.ping_sent_time = time.time() * 1000
            client.publish("esp32/ping", "sync")

            dots = (dots + 1) % 4
            sys.stdout.write(f"\r[-] Polling esp32/pong{'.' * dots:<3}")
            sys.stdout.flush()

            time.sleep(ping_interval)

        sys.stdout.write(f"\r[+] ESP32 Synced! Clock offset calculated: {self.clock_offset:.2f} ms\n\n")
        sys.stdout.flush()
        return True

    def print_live_stats(self):
        avg_lat = statistics.mean(self.latencies) if self.latencies else 0.0
        max_lat = max(self.latencies) if self.latencies else 0.0
        min_lat = min(self.latencies) if self.latencies else 0.0

        elapsed_sec = (
            ((time.time() * 1000 - self.first_packet_time) / 1000.0)
            if self.first_packet_time
            else 0.0
        )
        hz = (self.packet_count / elapsed_sec) if elapsed_sec > 0 else 0

        lines = [
            "=" * 44,
            "   LIVE BENCHMARK & MAIN HOOK DASHBOARD     ",
            "=" * 44,
            f" Total Packets   : {self.packet_count} ( {hz:.1f} Hz )",
            "-" * 44,
            f" Avg Latency     : {avg_lat:.2f} ms",
            f" Min Latency     : {min_lat:.2f} ms",
            f" Max Latency     : {max_lat:.2f} ms",
            "-" * 44,
            f" Last Action     : {self.last_action_msg}",
            f" Last Log        : {self.last_log_msg}",
            "-" * 44,
            " [1 / c] Trigger Config via Main",
            " [2 / h] Trigger Haptic via Main",
            " [q / ^C] Stop Test & Save Log",
            "=" * 44,
        ]

        if not self.is_first_print:
            sys.stdout.write(f"\033[{len(lines)}A")

        self.is_first_print = False

        # Leave one column unused to avoid terminal auto-wrapping. Keep log
        # messages on one physical row, including messages with control codes.
        width = max(1, shutil.get_terminal_size().columns - 1)
        for line in lines:
            line = "".join(char if char.isprintable() else " " for char in line)
            line = line.encode("ascii", errors="replace").decode("ascii")
            sys.stdout.write(f"\r{line[:width]}\033[K\n")

        sys.stdout.flush()

    def log_final_metrics(self):
        if not self.latencies or self.first_packet_time is None:
            print("[!] No latency metrics collected to log.")
            return

        file_exists = os.path.isfile(LOG_FILE)

        avg_lat = statistics.mean(self.latencies)
        max_lat = max(self.latencies)
        min_lat = min(self.latencies)
        elapsed_sec = (time.time() * 1000 - self.first_packet_time) / 1000.0
        hz = (self.packet_count / elapsed_sec) if elapsed_sec > 0 else 0
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        offset_val = f"{self.clock_offset:.2f}" if self.clock_offset is not None else "N/A"

        with open(LOG_FILE, mode="a", encoding="utf-8") as f:
            if not file_exists:
                f.write("Timestamp,Total Packets,Duration (s),Throughput (Hz),Avg Latency (ms),Min Latency (ms),Max Latency (ms),Clock Offset (ms)\n")

            f.write(f"{timestamp},{self.packet_count},{elapsed_sec:.2f},{hz:.2f},{avg_lat:.2f},{min_lat:.2f},{max_lat:.2f},{offset_val}\n")

        print(f"\n[+] Benchmark log written to: {LOG_FILE}")


def get_key_non_blocking():
    if select.select([sys.stdin], [], [], 0) == ([sys.stdin], [], []):
        return sys.stdin.read(1)
    return None


if __name__ == "__main__":
    client = create_mqtt_client()
    processor = TelemetryProcessor(client)
    benchmark = TelemetryBenchmark(processor)

    client.on_message = benchmark.on_message
    connect_with_retry(client, BROKER_HOST, BROKER_PORT)

    client.subscribe("esp32/pong")
    client.subscribe(TOPIC_SENSOR_RAW)
    client.loop_start()

    old_settings = termios.tcgetattr(sys.stdin)
    try:
        if benchmark.wait_for_clock_sync(client):
            tty.setcbreak(sys.stdin.fileno())

            try:
                with benchmark.dashboard_logging():
                    while True:
                        key = get_key_non_blocking()

                        if key in ("1", "c"):
                            processor.send_config()
                            benchmark.last_action_msg = "Sent Config via main processor"
                        elif key in ("2", "h"):
                            processor.trigger_haptic("1")
                            benchmark.last_action_msg = "Sent Haptic via main processor"
                        elif key == "q":
                            break

                        benchmark.print_live_stats()
                        time.sleep(0.1)

            finally:
                termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)

    except KeyboardInterrupt:
        pass

    finally:
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)
        print("\n\n[!] Benchmark stopped.")

        client.loop_stop()
        client.disconnect()
        benchmark.log_final_metrics()
