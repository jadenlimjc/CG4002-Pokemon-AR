"""Replaceable data sources for FPGA model evaluation.

Every source yields ``(window, label)`` where window has shape [6, window_size] (default: 128 samples at 50 Hz).
To add live sensor data later, implement the same ``__iter__`` contract; the
FPGA evaluator itself does not need to change.
"""

from pathlib import Path

import numpy as np


SCRIPT_DIR = Path(__file__).resolve().parent


def resolve_data_path(value):
    """Look beside this script for filenames; honor explicit directory paths."""
    path = Path(value).expanduser()
    if not path.is_absolute() and path.parent == Path("."):
        local = SCRIPT_DIR / path
        if local.is_file():
            return str(local.resolve())
    if path.is_file():
        return str(path.resolve())
    raise FileNotFoundError(
        f"Dataset not found: {path}. Place it in {SCRIPT_DIR}, or pass an existing path."
    )


class NPZIMUDataSource:
    """Load real/pre-recorded windows from an NPZ containing X and y arrays."""

    def __init__(self, path, sample_rate=50, window_size=128):
        self.sample_rate = sample_rate
        self.window_size = window_size
        path = resolve_data_path(path)
        with np.load(path) as dataset:
            self.windows = np.asarray(dataset["X"], dtype=np.float32).copy()
            self.labels = np.asarray(dataset["y"], dtype=np.int64).copy()
            self.class_names = (
                dataset["class_names"].tolist()
                if "class_names" in dataset else []
            )
            for key, expected in (("sample_rate_hz", sample_rate), ("window_size", window_size)):
                if key not in dataset:
                    raise ValueError(f"{path}: missing {key}; use a regenerated processed NPZ")
                if dataset[key].item() != expected:
                    raise ValueError(f"{path}: {key}={dataset[key].item()}, expected {expected}")
        if (self.windows.ndim != 3 or self.windows.shape[1:] != (6, window_size)
                or len(self.windows) == 0):
            raise ValueError(f"X must have nonempty shape [number_of_samples, 6, {window_size}]")
        if not np.isfinite(self.windows).all():
            raise ValueError("X contains NaN or infinity")
        if self.labels.shape != (len(self.windows),):
            raise ValueError("y must have one label per window")
        if not self.class_names:
            raise ValueError("class_names must be present and non-empty")
        if np.any(self.labels < 0) or np.any(self.labels >= len(self.class_names)):
            raise ValueError("y contains labels outside class_names")

    def __iter__(self):
        return iter(zip(self.windows, self.labels))
