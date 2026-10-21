"""Show live classifier results and timing for one or more ESP32 boards."""

from datetime import datetime
import logging
from pathlib import Path
import select
import sys
from threading import RLock
import time

# Support direct execution from any working directory.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from integration_support import live_client, parser_for, telemetry_device
from main import Action, InferenceWorker, TelemetryProcessor, TelemetryService
from process_telemetry import PacketError, decode_packet


class ResultTrace:
    """Serialize output and match each board's first gameplay event to a marker."""

    def __init__(self, expected=None, output=print):
        self.expected, self.output = expected, output
        self.lock = RLock()
        self.marker = None
        self.marked_devices = set()

    def emit(self, text):
        with self.lock:
            self.output(text, flush=True)

    def mark(self, now=None):
        with self.lock:
            self.marker = time.monotonic() if now is None else now
            self.marked_devices.clear()
            target = self.expected or "any gameplay event"
            self.emit(f"MARK {datetime.now().astimezone().isoformat(timespec='milliseconds')} "
                      f"waiting for {target} from a fresh window, separately for each board")

    def result(self, result, window, finished):
        stamp = datetime.fromtimestamp(result['timestamp_ms'] / 1000).astimezone().isoformat(timespec="milliseconds")
        timing = result['timing_ms']
        show = lambda value: "--" if value is None else f"{value:.2f}"
        with self.lock:
            line = (
                f"RESULT {stamp} [{result['model_id']}] {result['action']} "
                f"confidence={result['confidence']:.3f} {result['status']} "
                f"gameplay={result['published_action']} source={result['inference_source']} "
                f"sample_index={window.last_sequence} esp_ms={window.timestamp_ms} "
                f"receive_to_result_ms={show(timing['receive_to_result'])} "
                f"queue_ms={show(timing['queue'])} inference_ms={show(timing['inference'])} "
                f"skipped_windows={result['skipped_windows']}"
            )
            if (self.marker is not None and window.received_at is not None
                    and window.received_at >= self.marker
                    and result['model_id'] not in self.marked_devices
                    and result['status'] == 'PUBLISHED'
                    and (self.expected is None or result['action'] == self.expected)):
                line += f" mark_to_result_ms={(finished - self.marker) * 1000:.2f} (manual reference only)"
                self.marked_devices.add(result['model_id'])
            self.emit(line)
            ax, ay, az, gx, gy, gz, touch, any_touch = window.features[-1]
            self.emit(f"  Last processed sample: accel_g=({ax:.4f}, {ay:.4f}, {az:.4f}) "
                      f"gyro_dps=({gx:.4f}, {gy:.4f}, {gz:.4f}) "
                      f"touch_mask={int(touch)} any_touch={int(any_touch)}")
            if result['inference_source'] == 'fpga':
                self.emit("  FPGA ms: " + " ".join(
                    f"{key}={show(timing[key])}" for key in
                    ('total', 'input_preparation', 'dma', 'accelerator', 'output_copy')
                ) + " (DMA and accelerator overlap)")


class ProbeProcessor(TelemetryProcessor):
    def __init__(self, client, model_id, worker, trace, **kwargs):
        super().__init__(client, model_id, worker, **kwargs)
        self.trace = trace

    def process_packet(self, payload, received_at=None):
        super().process_packet(payload, received_at=received_at)
        size = len(self.buffer.buffer)
        if size < self.buffer.window_size and (size == 1 or size % self.buffer.hop_size == 0):
            self.trace.emit(f"[{self.model_id}] BUFFER {size}/{self.buffer.window_size}; waiting for a complete window")

    def run_inference(self, window):
        try:
            result = super().run_inference(window)
        except Exception as error:
            self.trace.emit(f"FAILED [{self.model_id}] sample_index={window.last_sequence}: {error}")
            raise
        self.trace.result(result, window, time.monotonic())
        return result


class ProcessingDemo(TelemetryService):
    def __init__(self, client, worker, trace, model_id=None, require_crc=False, max_devices=64):
        super().__init__(client, worker, max_devices,
                         processor_factory=lambda cli, device, owner: ProbeProcessor(cli, device, owner, trace))
        self.model_id, self.require_crc = model_id, require_crc

    def on_message(self, client, userdata, message):
        if telemetry_device(message, self.model_id) is None:
            return
        try:
            decode_packet(message.payload, require_crc=self.require_crc)
        except PacketError as error:
            logging.warning("Rejected packet: %s", error)
            return
        super().on_message(client, userdata, message)


def main():
    parser = parser_for(__doc__)
    parser.add_argument("--expect", type=str.upper, choices=[action.value for action in Action],
                        help="after Enter, measure until this classifier label produces a gameplay event")
    args = parser.parse_args()
    logging.getLogger().setLevel(logging.WARNING)
    trace = ResultTrace(args.expect)
    worker = InferenceWorker()
    client = live_client(parser, args, None, "processing-demo")
    demo = ProcessingDemo(client, worker, trace, args.model_id, args.require_crc)
    client.on_message = demo.on_message
    trace.emit(f"FPGA inference; confidence threshold={worker.confidence_threshold:.2f}. "
               "One accelerator/worker shared by all selected boards.")
    trace.emit("256-sample windows, 25-sample hop (~2.56 s warm-up, ~250 ms updates per board at 100 Hz).")
    trace.emit("receive_to_result_ms excludes network transit and earlier window samples. "
               "LOW_CONFIDENCE/SUPPRESSED results do not send a gameplay event.")
    trace.emit("Press Enter when starting a gesture; q + Enter or Ctrl-C stops. Keep the ESP32s in AUTO mode.")
    try:
        worker.start()
        client.loop_start()
        interactive = sys.stdin.isatty()
        while True:
            worker.raise_if_failed()
            if interactive and select.select([sys.stdin], [], [], 0.1)[0]:
                command = sys.stdin.readline()
                if not command or command.strip().lower() == "q":
                    break
                if not command.strip():
                    trace.mark()
            elif not interactive:
                worker.failed.wait(0.1)
    except KeyboardInterrupt:
        pass
    finally:
        worker.close()
        client.disconnect()
        client.loop_stop()


if __name__ == "__main__":
    main()
