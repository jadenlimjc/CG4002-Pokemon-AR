import numpy as np
import torch
import os
from model import Gesture1DCNN  # Import from the dedicated model file

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


def export_weights_and_vectors():
    """
    Loads the trained PyTorch model and exports its weights to a C-compatible
    header file and generates golden test vectors.
    """
    # Define output directory for HLS export files
    output_dir = r'.\hls_export'
    os.makedirs(output_dir, exist_ok=True)
    print(f"Output files will be saved to '{os.path.abspath(output_dir)}'")

    # 1. Load trained model
    device = torch.device('cpu')
    # Use the checkpoint file saved by train_baseline.py
    model_path = r'.\saved_checkpoints\gesture_1dcnn_best.pth'
    
    model = Gesture1DCNN()
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
            f.write('// This file is included by gesture_cnn.cpp\n\n')
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


    # 3. Export Golden Input and Output for HLS C-Simulation Testbench
    # Use a fixed seed for the dummy input to make the test reproducible
    torch.manual_seed(123)
    dummy_input = torch.randn(1, 6, 128)
    with torch.no_grad():
        dummy_output = model(dummy_input)

    golden_input_path = os.path.join(output_dir, 'golden_input.dat')
    golden_output_path = os.path.join(output_dir, 'golden_output.dat')

    np.savetxt(golden_input_path, dummy_input.numpy().flatten(), fmt='%.8f')
    np.savetxt(golden_output_path, dummy_output.numpy().flatten(), fmt='%.8f')
    print(f'Successfully generated {golden_input_path} and {golden_output_path} for testbench.')


if __name__ == '__main__':
    export_weights_and_vectors()
