"""Evaluate the FPGA accelerator and save its confusion matrix."""

import argparse
import os

import numpy as np

if __package__:
    from .cnn_pynq_ultra96 import GestureCNNAccelerator, NUM_CLASSES, OVERLAY_PATH
    from .evaluation_data import NPZIMUDataSource, SyntheticIMUDataSource
else:
    # Support copying these scripts to one directory on the Ultra96 and
    # invoking this file directly with ``python3 evaluate_fpga.py``.
    from cnn_pynq_ultra96 import GestureCNNAccelerator, NUM_CLASSES, OVERLAY_PATH
    from evaluation_data import NPZIMUDataSource, SyntheticIMUDataSource


CLASS_NAMES = [
    "Neutral", "Aim", "Throw", "Stop Aim", "Punch", "Downward Swipe", "Guard"
]


def evaluate(accelerator, data_source):
    """Return a [true, predicted] confusion matrix for any iterable source."""
    matrix = np.zeros((NUM_CLASSES, NUM_CLASSES), dtype=np.int64)
    count = 0
    for count, (window, target) in enumerate(data_source, start=1):
        target = int(target)
        if not 0 <= target < NUM_CLASSES:
            raise ValueError(f"Invalid label {target} at sample {count}")
        prediction = accelerator.predict(window)
        matrix[target, prediction] += 1
        print(
            f"\rProcessed {count} samples; latest true={target}, pred={prediction}",
            end="", flush=True
        )
    print()
    if count == 0:
        raise ValueError("The data source did not produce any samples")
    return matrix


def save_confusion_matrix(matrix, path, class_names=CLASS_NAMES):
    """Save a PNG when matplotlib is installed, plus an always-available CSV."""
    csv_path = os.path.splitext(path)[0] + ".csv"
    np.savetxt(csv_path, matrix, fmt="%d", delimiter=",")
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print(f"matplotlib is unavailable; saved numeric matrix to {csv_path}")
        return

    accuracy = 100.0 * np.trace(matrix) / matrix.sum()
    figure, axis = plt.subplots(figsize=(10, 8))
    image = axis.imshow(matrix, interpolation="nearest", cmap="Blues")
    figure.colorbar(image, ax=axis)
    axis.set(
        xticks=np.arange(NUM_CLASSES), yticks=np.arange(NUM_CLASSES),
        xticklabels=class_names, yticklabels=class_names,
        xlabel="Predicted Label", ylabel="True Label",
        title=f"FPGA Confusion Matrix (Accuracy: {accuracy:.2f}%)"
    )
    plt.setp(axis.get_xticklabels(), rotation=45, ha="right")
    threshold = matrix.max() / 2.0
    for row in range(NUM_CLASSES):
        for column in range(NUM_CLASSES):
            axis.text(column, row, str(matrix[row, column]), ha="center", va="center",
                      color="white" if matrix[row, column] > threshold else "black")
    figure.tight_layout()
    figure.savefig(path)
    plt.close(figure)
    print(f"Saved confusion matrix to {path} and {csv_path}")


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--overlay", default=OVERLAY_PATH)
    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument(
        "--data", help="NPZ with X [N,6,128], y [N], and optional class_names"
    )
    source_group.add_argument(
        "--synthetic", action="store_true",
        help="Explicitly use the legacy synthetic dataset"
    )
    parser.add_argument("--samples", type=int, default=300)
    parser.add_argument("--seed", type=int, default=123)
    parser.add_argument("--output", default="fpga_confusion_matrix.png")
    return parser.parse_args()


def main():
    args = parse_args()
    source = (NPZIMUDataSource(args.data) if args.data else
              SyntheticIMUDataSource(num_samples=args.samples, seed=args.seed))
    with GestureCNNAccelerator(args.overlay) as accelerator:
        matrix = evaluate(accelerator, source)
    accuracy = 100.0 * np.trace(matrix) / matrix.sum()
    print(f"Overall FPGA accuracy: {accuracy:.2f}% ({np.trace(matrix)}/{matrix.sum()})")
    print(matrix)
    save_confusion_matrix(matrix, args.output, source.class_names)


if __name__ == "__main__":
    main()
