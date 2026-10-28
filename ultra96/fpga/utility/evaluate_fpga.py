"""End-to-end board demo: accuracy, latency, throughput, and confusion matrix."""

import argparse
import csv
import os
from pathlib import Path
import sys

import numpy as np

if __package__:
    from ..deployment.cnn_pynq_ultra96 import GestureCNNAccelerator, NUM_CLASSES, OVERLAY_PATH
    from .evaluation_data import NPZIMUDataSource
else:
    # Find the sibling deployment directory even outside the repository root.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from deployment.cnn_pynq_ultra96 import GestureCNNAccelerator, NUM_CLASSES, OVERLAY_PATH
    from utility.evaluation_data import NPZIMUDataSource


DEPLOYMENT_DIR = Path(__file__).resolve().parents[1] / "deployment"


def resolve_data_path(value):
    """Honor explicit paths; also find bundled datasets by filename."""
    path = Path(value).expanduser()
    if path.is_file():
        return str(path.resolve())
    if not path.is_absolute() and path.parent == Path("."):
        bundled = DEPLOYMENT_DIR / path
        if bundled.is_file():
            return str(bundled)
    raise FileNotFoundError(
        f"Dataset not found: {path.resolve()}. "
        f"Place dataset filenames in {DEPLOYMENT_DIR}, or pass an existing path."
    )


def evaluate(accelerator, data_source, warmup=10, show_predictions=False):
    """Drive the low-level accelerator once per held-out test window."""
    # Confusion matrix uses [true class, predicted class].
    matrix = np.zeros((NUM_CLASSES, NUM_CLASSES), dtype=np.int64)
    timings = []
    count = 0
    for count, (window, target) in enumerate(data_source, start=1):
        target = int(target)
        if not 0 <= target < NUM_CLASSES:
            raise ValueError(f"Invalid label {target} at sample {count}")
        logits, timing = accelerator.predict_logits_timed(window)
        prediction = int(np.argmax(logits))
        # Warm-up samples count toward accuracy but not latency statistics.
        if count > warmup:
            timings.append(timing.as_dict())
        matrix[target, prediction] += 1
        if show_predictions:
            logit_text = ", ".join(
                f"{class_id}:{float(value):.6f}"
                for class_id, value in enumerate(logits)
            )
            print(
                f"Sample {count:3d}: true={target}, pred={prediction}, "
                f"logits=[{logit_text}]", flush=True
            )
        else:
            print(
                f"\rProcessed {count} samples; latest true={target}, pred={prediction}",
                end="", flush=True
            )
    if not show_predictions:
        print()
    if count == 0:
        raise ValueError("The data source did not produce any samples")
    if not timings:
        raise ValueError("Samples must exceed --warmup to produce benchmark data")
    return matrix, timings


def report_performance(timings, configured_clocks, csv_path=None):
    """Print benchmark statistics and optionally save every timed sample."""
    keys = list(timings[0])
    values = {key: np.asarray([row[key] for row in timings]) for key in keys}
    print(f"\nFPGA performance ({len(timings)} measured windows):")
    labels = {
        "total_s": "Total inference",
        "input_preparation_s": "Input preparation",
        "dma_s": "DMA send/receive (overlapped)",
        "dma_send_s": "DMA send channel",
        "dma_receive_s": "DMA receive channel",
        "accelerator_s": "Accelerator execution",
        "output_copy_s": "Output copy",
    }
    for key in keys:
        samples_ms = values[key] * 1e3
        print(f"  {labels[key]:31s} mean={samples_ms.mean():9.3f} ms  "
              f"median={np.median(samples_ms):9.3f} ms  "
              f"p95={np.percentile(samples_ms, 95):9.3f} ms")
    # End-to-end latency already includes overlapping DMA and accelerator time.
    total_time = values["total_s"].sum()
    print(f"  Throughput: {len(timings) / total_time:.2f} windows/s")
    print("  Note: DMA and accelerator intervals overlap; do not sum them.")
    if configured_clocks:
        clocks = ", ".join(f"{name}={mhz:.3f} MHz"
                           for name, mhz in configured_clocks.items())
        print(f"  Configured PL clock(s): {clocks}")
    else:
        print("  Configured PL clock(s): unavailable from overlay metadata")
    if csv_path:
        with open(csv_path, "w", newline="") as output:
            writer = csv.DictWriter(output, fieldnames=["sample"] + keys)
            writer.writeheader()
            for sample, row in enumerate(timings, start=1):
                writer.writerow({"sample": sample, **row})
        print(f"  Saved raw performance data to {csv_path}")


def save_confusion_matrix(matrix, path, class_names, title_prefix="FPGA"):
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
        title=f"{title_prefix} Confusion Matrix (Accuracy: {accuracy:.2f}%)"
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
    parser.add_argument(
        "--data", default=str(DEPLOYMENT_DIR / "real_gestures_test.npz"),
        help="NPZ with X [N,6,256], y [N], and class_names; defaults to the deployment dataset"
    )
    parser.add_argument("--warmup", type=int, default=10,
                        help="initial inferences excluded from performance results")
    parser.add_argument("--show-predictions", action="store_true",
                        help="print true class, predicted class, and all logits for every window")
    parser.add_argument(
        "--shuffle-labels", action="store_true",
        help="negative control: shuffle scoring labels, not input windows"
    )
    parser.add_argument(
        "--shuffle-seed", type=int, default=42,
        help="reproducible seed used by --shuffle-labels"
    )
    parser.add_argument("--performance-csv", default="fpga_performance.csv")
    parser.add_argument("--output", default="fpga_confusion_matrix.png")
    return parser.parse_args()


def main():
    args = parse_args()
    if args.warmup < 0:
        raise ValueError("--warmup must be non-negative")
    source = NPZIMUDataSource(resolve_data_path(args.data))
    if len(source.class_names) != NUM_CLASSES:
        raise ValueError(
            f"Dataset has {len(source.class_names)} classes but overlay expects "
            f"{NUM_CLASSES}; retrain/export/resynthesize the matching accelerator"
        )
    if args.shuffle_labels:
        # Negative control changes only labels used for scoring; inputs stay identical.
        original_labels = source.labels.copy()
        source.labels = np.random.default_rng(args.shuffle_seed).permutation(source.labels)
        changed = int(np.count_nonzero(source.labels != original_labels))
        print("=" * 72)
        print("NEGATIVE CONTROL: SCORING LABELS SHUFFLED; IMU WINDOWS UNCHANGED")
        print(f"Seed={args.shuffle_seed}; changed label positions={changed}/"
              f"{len(source.labels)}")
        print("=" * 72)
    else:
        print("GENUINE EVALUATION: original held-out labels")
    # Load the overlay once, then benchmark every held-out window.
    with GestureCNNAccelerator(args.overlay) as accelerator:
        matrix, timings = evaluate(accelerator, source, args.warmup,
                                   args.show_predictions)
        report_performance(timings, accelerator.configured_clock_mhz(),
                           args.performance_csv)
    accuracy = 100.0 * np.trace(matrix) / matrix.sum()
    mode = "Negative-Control FPGA" if args.shuffle_labels else "FPGA"
    print(f"Overall FPGA accuracy: {accuracy:.2f}% ({np.trace(matrix)}/{matrix.sum()})")
    print(matrix)
    save_confusion_matrix(matrix, args.output, source.class_names, mode)


if __name__ == "__main__":
    main()
