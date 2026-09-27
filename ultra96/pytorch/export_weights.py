import numpy as np
import torch
import argparse
import os
from model import Gesture1DCNN  # Import from the dedicated model file

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CHECKPOINT = os.path.join(
    SCRIPT_DIR, "saved_checkpoints", "gesture_1dcnn_real_100hz_256_best.pth"
)
DEFAULT_TEST_DATA = os.path.normpath(os.path.join(
    SCRIPT_DIR, "..", "real_data", "processed", "real_gestures_test.npz"
))

# --- This dictionary is the key to the solution ---
# It maps the complex PyTorch names to the simple C++ names.
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
    model_path=DEFAULT_CHECKPOINT,
    test_data_path=DEFAULT_TEST_DATA,
    output_dir=None,
):
    """
    Loads the trained PyTorch model and exports its weights to a C-compatible
    header file and generates golden test vectors.
    """
    # Define output directory for HLS export files
    output_dir = output_dir or os.path.join(SCRIPT_DIR, "hls_export")
    os.makedirs(output_dir, exist_ok=True)
    print(f"Output files will be saved to '{os.path.abspath(output_dir)}'")

    # 1. Load trained model
    device = torch.device('cpu')
    with np.load(test_data_path) as dataset:
        class_names = dataset["class_names"].tolist()
        test_windows = np.asarray(dataset["X"], dtype=np.float32)
    model = Gesture1DCNN(num_classes=len(class_names))
    try:
        model.load_state_dict(torch.load(model_path, map_location=device))
    except FileNotFoundError:
        print(f"ERROR: Model checkpoint '{model_path}' not found.")
        print("Please run train_baseline.py first to generate the model checkpoint.")
        return
        
    model.eval()
    state_dict = model.state_dict()

    # 2. Export weights to C header file using the explicit name map
    weights_path = os.path.join(output_dir, 'weights.h')
    try:
        with open(weights_path, 'w') as f:
            f.write('#ifndef WEIGHTS_H\n#define WEIGHTS_H\n\n')
            f.write('// Auto-generated weights for Vitis HLS\n')
            f.write('// This file is included by gesture_cnn.cpp\n')
            f.write(f'// Class order: {", ".join(class_names)}\n\n')
            f.write('#include "gesture_cnn.h"\n\n')

            for torch_name, c_name in NAME_MAP.items():
                if torch_name in state_dict:
                    param = state_dict[torch_name]
                    vals = param.detach().numpy().flatten()
                    vals_str = ', '.join(f'{v:.8f}' for v in vals)
                    
                    print(f"Exporting {torch_name} -> {c_name} (Shape: {param.shape})")
                    
                    f.write(f'const data_t {c_name}[{len(vals)}] = {{\n    {vals_str}\n}};\n\n')
                else:
                    print(f"WARNING: Parameter '{torch_name}' not found in model state_dict.")

            f.write('#endif // WEIGHTS_H\n')
        print(f"\nSuccessfully generated {weights_path}")
    except Exception as e:
        print(f"An error occurred while writing {weights_path}: {e}")


    # 3. Export a real, normalized held-out window and its PyTorch logits for
    # HLS C-simulation and board-level numerical comparison.
    if test_windows.ndim != 3 or test_windows.shape[1:] != (6, 256):
        raise ValueError(f"{test_data_path}: X must have shape [N, 6, 256]")
    dummy_input = torch.from_numpy(test_windows[:1].copy())
    with torch.no_grad():
        dummy_output = model(dummy_input)

    golden_input_path = os.path.join(output_dir, 'golden_input.dat')
    golden_output_path = os.path.join(output_dir, 'golden_output.dat')

    np.savetxt(golden_input_path, dummy_input.numpy().flatten(), fmt='%.8f')
    np.savetxt(golden_output_path, dummy_output.numpy().flatten(), fmt='%.8f')
    print(f'Successfully generated {golden_input_path} and {golden_output_path} for testbench.')


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", default=DEFAULT_CHECKPOINT)
    parser.add_argument("--test-data", default=DEFAULT_TEST_DATA)
    parser.add_argument("--output-dir", default=os.path.join(SCRIPT_DIR, "hls_export"))
    return parser.parse_args()


if __name__ == '__main__':
    args = parse_args()
    export_weights_and_vectors(args.checkpoint, args.test_data, args.output_dir)
