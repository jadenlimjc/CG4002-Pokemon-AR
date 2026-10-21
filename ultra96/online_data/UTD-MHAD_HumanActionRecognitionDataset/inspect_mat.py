from scipy.io import loadmat
from pathlib import Path

# Resolve the dataset relative to this script, regardless of the terminal's
# current working directory.
inertial_dir = Path(__file__).resolve().parent / "Inertial"
paths = sorted(inertial_dir.glob("*.mat"))
if not paths:
    raise FileNotFoundError(f"No .mat files found in {inertial_dir}")

path = paths[0]
print(f"Inspecting: {path}")
contents = loadmat(path)

print(contents.keys())

for name, value in contents.items():
    if not name.startswith("__"):
        print(f"{name}: shape={value.shape}, dtype={value.dtype}")
        print(value[:5])
