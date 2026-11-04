"""Export a matching checkpoint, fixed-point BN coefficients, and HLS test vectors.

Pass --test-data to select the sampling rate/window size. Without --checkpoint,
the newest completed matching real-data run is selected, including runs inside
configuration folders. Set vitis/gesture_cnn.h IN_LENGTH to the dataset window
size before exporting. All validation and BN compilation precede output writes.
"""
import numpy as np
import torch
import argparse
import json
import os
import re
import io
import sys
from pathlib import Path

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from ultra96.pytorch.training.model import Gesture1DCNN  # Import from the dedicated model file
from ultra96.pytorch.hls_export.bn_coefficients import generate_bn_coefficients
from ultra96.real_data.preprocess_for_training import CLASS_NAMES

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PYTORCH_DIR = os.path.dirname(SCRIPT_DIR)
ULTRA96_DIR = os.path.dirname(PYTORCH_DIR)
DEFAULT_OUTPUT_DIR = os.path.join(ULTRA96_DIR, "vitis")
DEFAULT_TEST_DATA = os.path.normpath(os.path.join(
    ULTRA96_DIR, "real_data", "processed_100hz_256", "real_gestures_test.npz"
))


HLS_HEADER = Path(DEFAULT_OUTPUT_DIR) / "gesture_cnn.h"


def resolve_checkpoint(model_path=None, checkpoint_dir=None, sample_rate=100, window_size=256):
    """Find the newest completed real-data run matching the requested input."""
    if model_path is not None:
        selected = Path(model_path).expanduser()
    else:
        root = Path(checkpoint_dir or Path(PYTORCH_DIR) / "saved_checkpoints")
        runs = []
        for metadata_path in root.rglob("run.json"):
            folder = metadata_path.parent
            metadata = json.loads(metadata_path.read_text())
            if (metadata.get("dataset") != "real" or not metadata.get("checkpoint") or
                    metadata.get("sample_rate_hz") != sample_rate or
                    metadata.get("window_size") != window_size):
                continue
            candidate = folder / Path(metadata["checkpoint"]).name
            if candidate.is_file():
                runs.append(candidate)
        if runs:
            selected = max(runs, key=lambda path: (path.parent.name, str(path)))
        else:
            selected = root / f"gesture_1dcnn_real_{sample_rate}hz_{window_size}_best.pth"
    if not selected.is_file():
        raise FileNotFoundError(
            f"No checkpoint for {sample_rate} Hz / {window_size} samples at {selected}. "
            "Train a matching model or pass --checkpoint PATH."
        )
    print(f"Selected checkpoint: {selected.resolve()}")
    return selected


def validate_hls_input(window_size):
    """Check the same header used by synthesis and the BN compilation helper."""
    text = HLS_HEADER.read_text()
    text = re.sub(r"/\*.*?\*/|//[^\n]*", "", text, flags=re.S)
    for name, expected in (("IN_CHANNELS", 6), ("IN_LENGTH", window_size), ("NUM_CLASSES", 11)):
        match = re.search(r"constexpr\s+int\s+" + name + r"\s*=\s*(\d+)\s*;", text)
        if match is None or int(match.group(1)) != expected:
            raise ValueError(f"Set {name} = {expected} in {HLS_HEADER} before exporting; "
                             "rebuild the HLS IP and FPGA bitstream for that configuration.")


# Map each trained PyTorch tensor to the name used by the HLS kernel.
NAME_MAP = {
    # Block 1
    "block1.0.weight": "conv1_weight",
    "block1.0.bias": "conv1_bias",
    "block1.1.weight": "bn1_weight",
    "block1.1.bias": "bn1_bias",
    "block1.1.running_mean": "bn1_running_mean",
    "block1.1.running_var": "bn1_running_var",
    # Block 2
    "block2.0.weight": "conv2_weight",
    "block2.0.bias": "conv2_bias",
    "block2.1.weight": "bn2_weight",
    "block2.1.bias": "bn2_bias",
    "block2.1.running_mean": "bn2_running_mean",
    "block2.1.running_var": "bn2_running_var",
    # Block 3
    "block3.0.weight": "conv3_weight",
    "block3.0.bias": "conv3_bias",
    "block3.1.weight": "bn3_weight",
    "block3.1.bias": "bn3_bias",
    "block3.1.running_mean": "bn3_running_mean",
    "block3.1.running_var": "bn3_running_var",
    # Classifier
    "classifier.1.weight": "fc1_weight",
    "classifier.1.bias": "fc1_bias",
    "classifier.3.weight": "fc2_weight",
    "classifier.3.bias": "fc2_bias",
}


def export_weights_and_vectors(
    model_path=None,
    test_data_path=DEFAULT_TEST_DATA,
    output_dir=None,
    hls_include_dir=None,
    cxx=None,
):
    """
    Loads the trained PyTorch model and exports its weights to a C-compatible
    header file and generates golden test vectors.

    BN scale/shift constants use the original fixed-point rounding. This needs
    a host C++ compiler and Vitis headers (--cxx and --hls-include-dir, or CXX
    and XILINX_HLS/XILINX_VITIS). Re-export after changing BN parameters or the
    fixed-point types/epsilon in gesture_cnn.h and precompute_bn.cpp.
    """
    # Validate everything before creating/replacing export artifacts.
    with np.load(test_data_path) as dataset:
        class_names = dataset["class_names"].tolist()
        test_windows = np.asarray(dataset["X"], dtype=np.float32)
        for key in ("sample_rate_hz", "window_size"):
            if key not in dataset:
                raise ValueError(f"{test_data_path}: missing {key}; regenerate the processed dataset")
        sample_rate = dataset["sample_rate_hz"].item()
        window_size = dataset["window_size"].item()
    if (type(sample_rate) is not int or not 1 <= sample_rate <= 100 or
            type(window_size) is not int or window_size < 4 or window_size % 4):
        raise ValueError("HLS requires an integer sample rate from 1 to 100 Hz and "
                         "a positive window size divisible by 4")
    if (test_windows.ndim != 3 or test_windows.shape[1:] != (6, window_size) or
            len(test_windows) == 0):
        raise ValueError(f"{test_data_path}: X must have nonempty shape [N, 6, {window_size}]")
    if not np.isfinite(test_windows).all():
        raise ValueError(f"{test_data_path}: X contains NaN or infinity")
    if class_names != CLASS_NAMES.tolist():
        raise ValueError("HLS export requires the real dataset's eleven classes in their original order")
    model_path = resolve_checkpoint(model_path, sample_rate=sample_rate, window_size=window_size)
    metadata_path = model_path.with_suffix(".json")
    if not metadata_path.is_file():
        raise ValueError(f"Missing checkpoint metadata: {metadata_path}. Use a checkpoint with its training JSON.")
    metadata = json.loads(metadata_path.read_text())
    for key, expected in (("sample_rate_hz", sample_rate), ("window_size", window_size),
                          ("class_names", class_names)):
        if metadata.get(key) != expected:
            raise ValueError(f"Checkpoint {key} does not match test dataset ({expected})")
    config = metadata["model_config"]
    expected_architecture = {"in_channels": 6, "num_classes": 11, "channels": [32, 64, 128],
                             "kernel_sizes": [7, 5, 3], "hidden_features": 64}
    for key, expected in expected_architecture.items():
        if config.get(key) != expected:
            raise ValueError(f"Current HLS requires {key}={expected}; checkpoint has {config.get(key)}")
    validate_hls_input(window_size)
    label = f"{sample_rate} Hz | {window_size}-sample window ({window_size / sample_rate:.2f} s)"
    print(f"Export configuration: {label}")
    model = Gesture1DCNN(**config)
    model.load_state_dict(torch.load(model_path, map_location="cpu", weights_only=True))
    model.eval()
    state_dict = model.state_dict()

    bn_parameters = {
        c_name: state_dict[torch_name].detach().numpy().flatten()
        for torch_name, c_name in NAME_MAP.items() if c_name.startswith("bn")
    }
    # Preserve the exact existing fixed-point BN calculation.
    bn_coefficients = generate_bn_coefficients(bn_parameters, hls_include_dir, cxx)
    golden_input = torch.from_numpy(test_windows[:1].copy())
    with torch.no_grad():
        golden_output = model(golden_input)
    if not torch.isfinite(golden_output).all():
        raise ValueError("Model produced non-finite golden logits")

    header = io.StringIO()
    header.write('#ifndef WEIGHTS_H\n#define WEIGHTS_H\n\n')
    header.write(f'// Auto-generated weights for Vitis HLS: {label}\n')
    header.write(f'// Checkpoint: {model_path.name}\n')
    header.write(f'// Class order: {", ".join(class_names)}\n\n')
    header.write('#include "gesture_cnn.h"\n\n')
    header.write(f'constexpr int EXPORTED_SAMPLE_RATE_HZ = {sample_rate};\n')
    header.write(f'constexpr int EXPORTED_WINDOW_SIZE = {window_size};\n')
    header.write('static_assert(IN_LENGTH == EXPORTED_WINDOW_SIZE, "Weights/window size mismatch; re-export");\n\n')
    for torch_name, c_name in NAME_MAP.items():
        param = state_dict[torch_name]
        values = param.detach().numpy().flatten()
        literals = ', '.join(f'{v:.8f}' for v in values)
        print(f"Exporting {torch_name} -> {c_name} (Shape: {param.shape})")
        header.write(f'const data_t {c_name}[{len(values)}] = {{\n    {literals}\n}};\n\n')
    header.write(bn_coefficients)
    header.write('static_assert(sizeof(fc2_weight) / sizeof(fc2_weight[0]) == '
                 '64 * NUM_CLASSES, "Re-export weights for the HLS class count");\n')
    header.write('static_assert(sizeof(fc2_bias) / sizeof(fc2_bias[0]) == '
                 'NUM_CLASSES, "Re-export weights for the HLS class count");\n\n')
    header.write('#endif // WEIGHTS_H\n')

    output_dir = Path(output_dir or DEFAULT_OUTPUT_DIR)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / 'weights.h').write_text(header.getvalue())
    np.savetxt(output_dir / 'golden_input.dat', golden_input.numpy().flatten(), fmt='%.8f')
    np.savetxt(output_dir / 'golden_output.dat', golden_output.numpy().flatten(), fmt='%.8f')
    manifest = {"sample_rate_hz": sample_rate, "window_size": window_size,
                "input_shape": [6, window_size], "class_names": class_names,
                "model_config": config, "checkpoint": str(model_path.resolve()),
                "test_data": str(Path(test_data_path).resolve()), "golden_sample_index": 0,
                "hls_header": str(HLS_HEADER.resolve())}
    (output_dir / 'export.json').write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Exported {label} to {output_dir.resolve()}")


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", default=None,
                        help="checkpoint path; defaults to the latest completed real-data run matching the test dataset")
    parser.add_argument("--test-data", default=DEFAULT_TEST_DATA,
                        help="processed real test NPZ; its metadata selects sampling rate and window size")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--hls-include-dir", help="Vitis include directory for exact BN precomputation")
    parser.add_argument("--cxx", help="Host C++ compiler command (default: CXX or g++)")
    return parser.parse_args()


if __name__ == '__main__':
    args = parse_args()
    export_weights_and_vectors(args.checkpoint, args.test_data, args.output_dir,
                               args.hls_include_dir, args.cxx)
