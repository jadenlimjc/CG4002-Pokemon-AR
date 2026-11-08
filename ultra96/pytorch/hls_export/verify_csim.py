"""Compare a compiled HLS testbench with PyTorch on real windows.

By default checks one example per class; --all checks the complete test set.
The C++ testbench also checks each inference against its fixed-point reference.
"""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

import numpy as np
import torch

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from ultra96.pytorch.training.model import Gesture1DCNN
from ultra96.pytorch.hls_export.bn_coefficients import _find_hls_include, _find_compiler

ULTRA96 = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable", type=Path, default=ULTRA96 / "vitis/build/gesture_cnn/solution1/csim/build/csim.exe")
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--data", type=Path, default=ULTRA96 / "real_data/processed_50hz_128/real_gestures_test.npz")
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--all", action="store_true")
    selection.add_argument("--indices", type=int, nargs="+")
    parser.add_argument("--output", type=Path, default=ULTRA96 / "vitis/csim_validation.json")
    parser.add_argument("--hls-include-dir", help="Vitis include directory (auto-detected by default)")
    args = parser.parse_args()
    torch.set_num_threads(2)
    metadata = json.loads(args.checkpoint.with_suffix(".json").read_text())
    model = Gesture1DCNN(**metadata["model_config"]).eval()
    model.load_state_dict(torch.load(args.checkpoint, map_location="cpu", weights_only=True))
    executable = args.executable.resolve(strict=True)
    environment = os.environ.copy()
    if sys.platform == "win32":
        # Match the runtime DLL paths used by Vitis's generated run_sim.tcl.
        include = _find_hls_include(args.hls_include_dir)
        runtime_dirs = [include.parent / "win64/csim",
                        Path(_find_compiler(include)[0]).parent]
        runtime_dirs.extend((include.parent / "win64/tools").glob("*"))
        environment["PATH"] = os.pathsep.join(str(p) for p in runtime_dirs) + os.pathsep + environment.get("PATH", "")
    with np.load(args.data) as data:
        windows, labels = data["X"].copy(), data["y"].copy()
        names = data["class_names"].tolist()
        if names != metadata["class_names"]:
            raise ValueError("Dataset/checkpoint class order differs")
        for key in ("sample_rate_hz", "window_size"):
            if data[key].item() != metadata[key]:
                raise ValueError(f"Dataset/checkpoint {key} differs")
    indices = (list(range(len(labels))) if args.all else args.indices
               if args.indices is not None else [int(np.flatnonzero(labels == c)[0]) for c in np.unique(labels)])
    if not indices or any(i < 0 or i >= len(labels) for i in indices):
        raise ValueError("Sample indices must refer to existing test windows")
    with torch.no_grad():
        expected = model(torch.from_numpy(windows[indices]).float()).numpy()
    actual = []
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="csim_check_", dir=args.output.parent) as tmp:
        root = Path(tmp).resolve()
        for i in indices:
            np.savetxt(root / "input.dat", windows[i].reshape(-1), fmt="%.8f")
            result = subprocess.run([str(executable), str(root / "input.dat"), str(root / "output.dat")],
                                    cwd=root, env=environment, text=True, capture_output=True, timeout=120)
            if result.returncode:
                raise RuntimeError(f"C simulation failed for window {i} (exit {result.returncode}):\n{result.stdout}\n{result.stderr}")
            logits = np.loadtxt(root / "output.dat", dtype=np.float32).reshape(-1)
            if logits.shape != (len(names),) or not np.isfinite(logits).all():
                raise ValueError(f"Invalid C simulation logits for window {i}")
            actual.append(logits)
            print(f"Verified C++ fixed-point reference: window {i}", flush=True)
    actual = np.asarray(actual)
    close = np.isclose(actual, expected, rtol=0.10, atol=0.50)
    floating_predictions, fixed_predictions = expected.argmax(1), actual.argmax(1)
    report = {"checkpoint": str(args.checkpoint.resolve()), "dataset": str(args.data.resolve()),
              "indices": indices, "samples": len(indices),
              "max_absolute_logit_error": float(np.abs(actual - expected).max()),
              "all_logits_within_tolerance": bool(close.all()), "rtol": 0.10, "atol": 0.50,
              "prediction_agreement_percent": float(100 * np.mean(floating_predictions == fixed_predictions)),
              "pytorch_accuracy_percent": float(100 * np.mean(floating_predictions == labels[indices])),
              "fixed_point_accuracy_percent": float(100 * np.mean(fixed_predictions == labels[indices])),
              "pytorch_predictions": floating_predictions.tolist(),
              "fixed_point_predictions": fixed_predictions.tolist()}
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    if not close.all():
        raise SystemExit("Fixed-point logits exceed the deployment tolerance; inspect the saved report")


if __name__ == "__main__":
    main()
