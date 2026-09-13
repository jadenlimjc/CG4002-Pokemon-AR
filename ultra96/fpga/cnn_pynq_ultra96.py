from pynq import Overlay, allocate
import numpy as np
import os

# Keep all deployment artifacts beside this script so the directory can be
# copied to the board as one self-contained bundle.
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# --- Configuration for the Gesture CNN ---
IN_CHANNELS = 6
IN_LENGTH = 128
NUM_CLASSES = 7

INPUT_DATA_SIZE = IN_CHANNELS * IN_LENGTH  # 6 * 128 = 768 floats
OUTPUT_DATA_SIZE = NUM_CLASSES             # 7 floats (logits)

# PYNQ loads the Vivado-generated .bit file and parses a same-named .hwh file.
# Resolve it relative to this script so the bundle can be moved as a unit.
OVERLAY_PATH = os.path.join(SCRIPT_DIR, "gesture_cnn.bit")
INPUT_PATH = os.path.join(SCRIPT_DIR, "golden_input.dat")
REFERENCE_OUTPUT_PATH = os.path.join(SCRIPT_DIR, "golden_output.dat")

# PyTorch is floating-point while the accelerator is fixed-point, so these
# tolerances measure quantization error rather than bit-exact equivalence.
REFERENCE_RTOL = 0.10
REFERENCE_ATOL = 0.50


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


class GestureCNNAccelerator:
    """Reusable single-window inference interface for the FPGA CNN."""

    def __init__(self, overlay_path=OVERLAY_PATH):
        hwh_path = os.path.splitext(overlay_path)[0] + ".hwh"
        if not os.path.exists(overlay_path):
            raise FileNotFoundError(f"Bitstream not found: {overlay_path}")
        if not os.path.exists(hwh_path):
            raise FileNotFoundError(
                f"Hardware handoff not found: {hwh_path}. The .bit and .hwh "
                "files must have the same basename."
            )

        self.overlay = Overlay(overlay_path)
        self.dma = get_dma_instance(self.overlay)
        self.cnn = get_cnn_instance(self.overlay)
        self.in_buf = allocate(shape=(INPUT_DATA_SIZE,), dtype=np.float32)
        self.out_buf = allocate(shape=(OUTPUT_DATA_SIZE,), dtype=np.float32)
        self._closed = False

    def predict_logits(self, window):
        """Run one [6, 128] channel-major window and return seven logits."""
        if self._closed:
            raise RuntimeError("Accelerator has already been closed")

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

        # Arm receive first to avoid output backpressure, then start the IP.
        self.dma.recvchannel.transfer(self.out_buf)
        self.cnn.write(0x00, 0x01)
        self.dma.sendchannel.transfer(self.in_buf)
        self.dma.sendchannel.wait()
        self.dma.recvchannel.wait()
        return np.array(self.out_buf, dtype=np.float32, copy=True)

    def predict(self, window):
        return int(np.argmax(self.predict_logits(window)))

    def close(self):
        if not self._closed:
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
    overlay = Overlay(OVERLAY_PATH)
    print("Overlay loaded")
    
    print("Discovered IP blocks:", list(overlay.ip_dict.keys()))
    dma = get_dma_instance(overlay)
    cnn = get_cnn_instance(overlay)

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

    # The exported file/PyTorch tensor is channel-major [C, L], while the HLS
    # streaming convolution consumes all channels at each timestep [L, C].
    stream_input = input_data.reshape(IN_CHANNELS, IN_LENGTH).T.reshape(-1)

    in_buf = allocate(shape=(INPUT_DATA_SIZE,), dtype=np.float32)
    out_buf = allocate(shape=(OUTPUT_DATA_SIZE,), dtype=np.float32)

    try:
        in_buf[:] = stream_input
        out_buf.fill(0)

        print(f"Starting DMA transfer: {INPUT_DATA_SIZE} in, {OUTPUT_DATA_SIZE} out")
        # Arm the receive path before starting the accelerator so output-side
        # backpressure cannot stall the pipeline. The AXI-Lite control bundle
        # generated by HLS uses bit 0 of address 0x00 as ap_start.
        dma.recvchannel.transfer(out_buf)
        cnn.write(0x00, 0x01)
        dma.sendchannel.transfer(in_buf)
        dma.sendchannel.wait()
        dma.recvchannel.wait()
        print("DMA transfer complete")

        received_output = np.array(out_buf, dtype=np.float32)

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

    finally:
        in_buf.freebuffer()
        out_buf.freebuffer()


if __name__ == "__main__":
    main()
