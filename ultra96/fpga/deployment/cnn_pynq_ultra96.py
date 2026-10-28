from pynq import Overlay, allocate
import numpy as np
import os
import logging
from dataclasses import asdict, dataclass
from time import perf_counter_ns, sleep

# Keep all deployment artifacts beside this script so the directory can be
# copied to the board as one self-contained bundle.
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# --- Configuration for the Gesture CNN ---
IN_CHANNELS = 6
IN_LENGTH = 256
NUM_CLASSES = 11

INPUT_DATA_SIZE = IN_CHANNELS * IN_LENGTH  # 6 * 256 = 1536 floats
OUTPUT_DATA_SIZE = NUM_CLASSES             # 11 floats (logits)

# PYNQ loads the Vivado-generated .bit file and parses a same-named .hwh file.
# Resolve it relative to this script so the bundle can be moved as a unit.
OVERLAY_PATH = os.path.join(SCRIPT_DIR, "gesture_cnn.bit")


def golden_vector_path(filename):
    """Prefer a board-local vector, then the repository's Vitis export."""
    local = os.path.join(SCRIPT_DIR, filename)
    if os.path.isfile(local):
        return local
    exported = os.path.abspath(os.path.join(SCRIPT_DIR, "..", "..", "vitis", filename))
    return exported if os.path.isfile(exported) else local


INPUT_PATH = golden_vector_path("golden_input.dat")
REFERENCE_OUTPUT_PATH = golden_vector_path("golden_output.dat")

# PyTorch is floating-point while the accelerator is fixed-point, so these
# tolerances measure quantization error rather than bit-exact equivalence.
REFERENCE_RTOL = 0.10
REFERENCE_ATOL = 0.50
ACCELERATOR_TIMEOUT_S = 10.0
DMA_TIMEOUT_S = 10.0
DMA_STOP_TIMEOUT_S = 1.0
POLL_INTERVAL_S = 0.0001


def wait_for_dma(channel, name, timeout_s=DMA_TIMEOUT_S):
    """Bound a simple DMA wait while preserving PYNQ's cache cleanup."""
    deadline = perf_counter_ns() + int(timeout_s * 1e9)
    while True:
        if channel.error:
            raise RuntimeError(f"DMA {name} channel reported a hardware error")
        if not channel.running:
            raise RuntimeError(f"DMA {name} channel halted before completion")
        if channel.idle:
            # The single inference owner guarantees completion stays stable.
            # PYNQ wait now returns immediately and invalidates receive cache.
            channel.wait()
            return
        if perf_counter_ns() >= deadline:
            raise TimeoutError(f"DMA {name} did not complete within {timeout_s:g} seconds")
        sleep(POLL_INTERVAL_S)


@dataclass(frozen=True)
class InferenceTiming:
    """Host-observed timings for one inference, expressed in seconds.

    The DMA channels and accelerator operate concurrently, so ``dma_s``,
    ``dma_send_s``, ``dma_receive_s`` and ``accelerator_s`` overlap and must
    not be added together. ``total_s`` is the complete user-visible latency.
    """

    total_s: float
    input_preparation_s: float
    dma_s: float
    dma_send_s: float
    dma_receive_s: float
    accelerator_s: float
    output_copy_s: float

    def as_dict(self):
        return asdict(self)


def get_overlay_ip(overlay, name):
    """Resolve either a top-level IP name or an IP inside a hierarchy."""
    instance = overlay
    for component in name.split('/'):
        instance = getattr(instance, component)
    return instance

def get_dma_instance(ol):
    if hasattr(ol, "axi_dma_0"):
        return ol.axi_dma_0

    dma_names = [
        name for name, desc in ol.ip_dict.items()
        if "axi_dma" in desc.get("type", "").lower() or "axi_dma" in name.lower()
    ]
    if dma_names:
        print(f"Using detected DMA instance: {dma_names[0]}")
        return get_overlay_ip(ol, dma_names[0])
    raise RuntimeError("No AXI DMA instance found in overlay.ip_dict")


def get_cnn_instance(ol):
    cnn_names = [
        name for name, desc in ol.ip_dict.items()
        if "gesture_cnn" in name.lower()
        or "gesture_cnn" in desc.get("type", "").lower()
    ]
    if not cnn_names:
        raise RuntimeError(
            "No gesture_cnn HLS IP found. Check that it is present in the "
            "block design and that the matching .hwh file was copied."
        )

    print(f"Using detected CNN instance: {cnn_names[0]}")
    return get_overlay_ip(ol, cnn_names[0])


def clear_stale_overlay_state():
    """Recover when PYNQ remembers a bitstream that has been moved/deleted."""
    from pynq.pl_server.global_state import (
        clear_global_state, global_state_file_exists, load_global_state,
    )

    if not global_state_file_exists():
        return
    try:
        load_global_state()
    except FileNotFoundError as error:
        # Loading state hashes the previously loaded bitstream. Only recover
        # that failure; malformed state and unrelated missing files must surface.
        missing = os.fsdecode(error.filename) if error.filename is not None else ""
        if not missing.lower().endswith(".bit") or os.path.exists(missing):
            raise
        logging.getLogger(__name__).warning(
            "Clearing stale PYNQ state referencing missing bitstream: %s", missing
        )
        clear_global_state()


class GestureCNNAccelerator:
    """Low-level Overlay, DMA, and MMIO driver used by evaluate_fpga.py."""

    def __init__(self, overlay_path=OVERLAY_PATH):
        overlay_path = os.path.abspath(os.path.expanduser(os.fspath(overlay_path)))
        hwh_path = os.path.splitext(overlay_path)[0] + ".hwh"
        if not os.path.exists(overlay_path):
            raise FileNotFoundError(f"Bitstream not found: {overlay_path}")
        if not os.path.exists(hwh_path):
            raise FileNotFoundError(
                f"Hardware handoff not found: {hwh_path}. The .bit and .hwh "
                "files must have the same basename."
            )

        # Program the FPGA and discover IP blocks from the matching HWH file.
        clear_stale_overlay_state()
        self.overlay = Overlay(overlay_path)
        self.dma = get_dma_instance(self.overlay)
        self.cnn = get_cnn_instance(self.overlay)
        # DMA requires physically contiguous input and output buffers.
        self.in_buf = allocate(shape=(INPUT_DATA_SIZE,), dtype=np.float32)
        self.out_buf = allocate(shape=(OUTPUT_DATA_SIZE,), dtype=np.float32)
        self._closed = False
        self._faulted = False
        self.last_timing = None

    def configured_clock_mhz(self):
        """Return runtime PL clock(s) reported by PYNQ, when available."""
        clocks = getattr(self.overlay, "clock_dict", None) or {}
        result = {}
        for name, description in clocks.items():
            value = description.get("frequency") if isinstance(description, dict) else None
            if value is not None:
                # PYNQ releases have represented this value in either Hz or MHz.
                value = float(value)
                result[name] = value / 1e6 if value > 1e5 else value
        return result

    def predict_logits(self, window):
        """Run one [6, 256] channel-major window and return eleven logits."""
        logits, timing = self.predict_logits_timed(window)
        self.last_timing = timing
        return logits

    def predict_logits_timed(self, window):
        """Run one window and return ``(logits, InferenceTiming)``.

        ``accelerator_s`` is measured from ``ap_start`` until ``ap_done`` is
        observed. It includes any time the core is stalled by its AXI streams.
        DMA timings are host-observed channel intervals and include overlap.
        """
        if self._closed:
            raise RuntimeError("Accelerator has already been closed")

        if self._faulted:
            raise RuntimeError("Accelerator faulted; close and reload the overlay before retrying")
        self.last_timing = None
        total_start = perf_counter_ns()
        preparation_start = total_start
        window = np.asarray(window, dtype=np.float32)
        if window.shape != (IN_CHANNELS, IN_LENGTH):
            raise ValueError(
                f"Expected input shape {(IN_CHANNELS, IN_LENGTH)}, "
                f"received {window.shape}"
            )

        # The HLS stream consumes every channel for a timestep before moving
        # to the next timestep, unlike the channel-major model/data format.
        self.in_buf[:] = np.ascontiguousarray(window.T).reshape(-1)
        self.out_buf.fill(0)
        preparation_end = perf_counter_ns()

        try:
            # Arm receive first to prevent output back-pressure, then send input.
            receive_start = perf_counter_ns()
            self.dma.recvchannel.transfer(self.out_buf)
            send_start = perf_counter_ns()
            self.dma.sendchannel.transfer(self.in_buf)
            accelerator_start = perf_counter_ns()
            # AXI-Lite control register: bit 0 starts the HLS accelerator.
            self.cnn.write(0x00, 0x01)

            # The send wait gives an accurate host-observed input-channel interval.
            # Input must finish before this finite-input accelerator can assert done.
            wait_for_dma(self.dma.sendchannel, "send")
            send_end = perf_counter_ns()

            # Poll AXI-Lite bit 1 until the accelerator reports ap_done.
            timeout_ns = int(ACCELERATOR_TIMEOUT_S * 1e9)
            while not (self.cnn.read(0x00) & 0x02):
                if perf_counter_ns() - accelerator_start > timeout_ns:
                    raise TimeoutError(
                        f"Accelerator did not assert ap_done within "
                        f"{ACCELERATOR_TIMEOUT_S:g} seconds"
                    )
                sleep(POLL_INTERVAL_S)
            accelerator_end = perf_counter_ns()
            wait_for_dma(self.dma.recvchannel, "receive")
            receive_end = perf_counter_ns()
        except Exception:
            # Partial transfers require overlay recovery before reuse.
            self._faulted = True
            raise

        copy_start = perf_counter_ns()
        logits = np.array(self.out_buf, dtype=np.float32, copy=True)
        total_end = perf_counter_ns()
        scale = 1e-9
        timing = InferenceTiming(
            total_s=(total_end - total_start) * scale,
            input_preparation_s=(preparation_end - preparation_start) * scale,
            dma_s=(receive_end - receive_start) * scale,
            dma_send_s=(send_end - send_start) * scale,
            dma_receive_s=(receive_end - receive_start) * scale,
            accelerator_s=(accelerator_end - accelerator_start) * scale,
            output_copy_s=(total_end - copy_start) * scale,
        )
        self.last_timing = timing
        return logits, timing

    def predict(self, window):
        return int(np.argmax(self.predict_logits(window)))

    def close(self):
        if not self._closed:
            # PYNQ stop() also waits indefinitely. Request halt directly, then
            # bound acknowledgement before releasing DMA-owned memory.
            for offset in (0x00, 0x30):
                self.dma.mmio.write(offset, 0)
            deadline = perf_counter_ns() + int(DMA_STOP_TIMEOUT_S * 1e9)
            while self.dma.sendchannel.running or self.dma.recvchannel.running:
                if perf_counter_ns() >= deadline:
                    self._faulted = True
                    raise TimeoutError("DMA did not halt; buffers retained. Reset hardware before recovery.")
                sleep(POLL_INTERVAL_S)
            self.in_buf.freebuffer()
            self.out_buf.freebuffer()
            self._closed = True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

def main():
    hwh_path = os.path.splitext(OVERLAY_PATH)[0] + ".hwh"
    if not os.path.exists(OVERLAY_PATH):
        raise FileNotFoundError(f"Bitstream not found: {OVERLAY_PATH}")
    if not os.path.exists(hwh_path):
        raise FileNotFoundError(
            f"Hardware handoff not found: {hwh_path}. The .bit and .hwh "
            "files must have the same basename."
        )

    print(f"Loading overlay: {OVERLAY_PATH}")
    # Load the golden input vector generated by export_weights.py
    # This ensures we test the hardware with the exact same data as the HLS C-simulation.
    if not os.path.exists(INPUT_PATH):
        raise FileNotFoundError(
            f"Golden input not found: {INPUT_PATH}. Copy golden_input.dat "
            "beside this script."
        )

    input_data = np.loadtxt(INPUT_PATH, dtype=np.float32).reshape(-1)

    if input_data.size != INPUT_DATA_SIZE:
        raise RuntimeError(f"Input size mismatch: loaded {input_data.size} floats, expected {INPUT_DATA_SIZE}")

    # A reference output is optional: inference itself requires only NumPy and
    # PYNQ. Generate/copy this file on the development machine if validation
    # against known logits is desired.
    expected_output = None
    if os.path.exists(REFERENCE_OUTPUT_PATH):
        expected_output = np.loadtxt(
            REFERENCE_OUTPUT_PATH, dtype=np.float32
        ).reshape(-1)
        if expected_output.size != OUTPUT_DATA_SIZE:
            raise RuntimeError(
                "Reference output size mismatch: loaded "
                f"{expected_output.size} floats, expected {OUTPUT_DATA_SIZE}"
            )

    with GestureCNNAccelerator(OVERLAY_PATH) as accelerator:
        print("Overlay loaded")
        print("Discovered IP blocks:", list(accelerator.overlay.ip_dict.keys()))
        received_output = accelerator.predict_logits(
            input_data.reshape(IN_CHANNELS, IN_LENGTH)
        )

        print("Received values:")
        print(received_output)
        hardware_class = int(np.argmax(received_output))
        print(f"Hardware class: {hardware_class}")

        if expected_output is None:
            print(
                "Reference validation skipped: golden_output.dat was not "
                "found beside the script."
            )
        else:
            print("Expected values:")
            print(expected_output)

            close_mask = np.isclose(
                received_output,
                expected_output,
                rtol=REFERENCE_RTOL,
                atol=REFERENCE_ATOL,
            )
            numeric_close = bool(np.all(close_mask))
            reference_class = int(np.argmax(expected_output))
            class_match = hardware_class == reference_class

            print(f"Reference class: {reference_class}")
            print(f"Class match: {class_match}")
            print(f"Logits within fixed-point tolerance: {numeric_close}")

            if not numeric_close:
                mismatch = np.where(~close_mask)[0]
                print(f"Total mismatches: {mismatch.size}")
                for idx in mismatch:
                    print(
                        f"idx {idx}: received={received_output[idx]}, "
                        f"expected={expected_output[idx]}"
                    )
            else:
                print("All logits are within the configured tolerance.")

            if not class_match or not numeric_close:
                raise RuntimeError(
                    "Hardware verification failed: "
                    f"class_match={class_match}, numeric_close={numeric_close}"
                )



if __name__ == "__main__":
    main()
