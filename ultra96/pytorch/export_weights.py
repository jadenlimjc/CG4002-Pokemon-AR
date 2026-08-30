import numpy as np
import torch
from train_baseline import Gesture1DCNN
import os

# Define the output directory
output_dir = 'hls_export'
os.makedirs(output_dir, exist_ok=True)

# 1. Load trained model
device = torch.device('cpu')
model_path = os.path.join('saved_checkpoints', 'gesture_1dcnn_best.pth')
model = Gesture1DCNN()
model.load_state_dict(torch.load(model_path, map_location=device))
model.eval()
print(f"Loaded trained model from '{model_path}'.")

# 2. Export weights to C header
weights_h_path = os.path.join(output_dir, 'weights.h')
with open(weights_h_path, 'w') as f:
  f.write('#ifndef WEIGHTS_H\n#define WEIGHTS_H\n\n')
  f.write('// Auto-generated weights for Vitis HLS\n\n')
  for name, param in model.named_parameters():
    c_name = name.replace('.', '_')
    vals = param.detach().numpy().flatten()
    vals_str = ', '.join(f'{v:.6f}f' for v in vals)
    f.write(
        f'const float {c_name}[{len(vals)}] = {{\n    {vals_str}\n}};\n\n'
    )
  f.write('#endif // WEIGHTS_H\n')

print(f"Generated '{weights_h_path}' successfully.")

# 3. Export Golden Input and Output for HLS C-Simulation Testbench
dummy_input = torch.randn(1, 6, 128)
with torch.no_grad():
  dummy_output = model(dummy_input)

golden_input_path = os.path.join(output_dir, 'golden_input.dat')
golden_output_path = os.path.join(output_dir, 'golden_output.dat')

np.savetxt(golden_input_path, dummy_input.numpy().flatten(), fmt='%.6f')
np.savetxt(golden_output_path, dummy_output.numpy().flatten(), fmt='%.6f')
print(f"Generated '{golden_input_path}' and '{golden_output_path}' for testbench.")
