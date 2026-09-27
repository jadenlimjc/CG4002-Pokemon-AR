"""Replaceable data sources for FPGA model evaluation.

Every source yields ``(window, label)`` where window has shape [6, 256].
To add live sensor data later, implement the same ``__iter__`` contract; the
FPGA evaluator itself does not need to change.
"""

import numpy as np


class NPZIMUDataSource:
    """Load real/pre-recorded windows from an NPZ containing X and y arrays."""

    def __init__(self, path):
        with np.load(path) as dataset:
            self.windows = np.asarray(dataset["X"], dtype=np.float32).copy()
            self.labels = np.asarray(dataset["y"], dtype=np.int64).copy()
            self.class_names = (
                dataset["class_names"].tolist()
                if "class_names" in dataset else []
            )
        if self.windows.ndim != 3 or self.windows.shape[1:] != (6, 256):
            raise ValueError("X must have shape [number_of_samples, 6, 256]")
        if self.labels.shape != (len(self.windows),):
            raise ValueError("y must have one label per window")
        if not self.class_names:
            raise ValueError("class_names must be present and non-empty")

    def __iter__(self):
        return iter(zip(self.windows, self.labels))
