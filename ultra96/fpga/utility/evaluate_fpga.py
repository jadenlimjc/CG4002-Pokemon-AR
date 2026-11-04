"""End-to-end board demo: accuracy, latency, throughput, and confusion matrix."""

import argparse
import csv
import json
import os
from pathlib import Path
import sys

import numpy as np

SCRIPT_DIR = Path(__file__).resolve().parent

if __package__:
    from ..deployment.cnn_pynq_ultra96 import GestureCNNAccelerator, NUM_CLASSES, IN_LENGTH, SAMPLE_RATE_HZ
    from .evaluation_data import NPZIMUDataSource, resolve_data_path
else:
    # A board bundle can contain all three scripts in the same directory.
    if (SCRIPT_DIR / "cnn_pynq_ultra96.py").is_file():
        from cnn_pynq_ultra96 import GestureCNNAccelerator, NUM_CLASSES, IN_LENGTH, SAMPLE_RATE_HZ
    else:
        # Also support the repository's sibling deployment/utility layout.
        sys.path.insert(0, str(SCRIPT_DIR.parent))
        from deployment.cnn_pynq_ultra96 import GestureCNNAccelerator, NUM_CLASSES, IN_LENGTH, SAMPLE_RATE_HZ
    from evaluation_data import NPZIMUDataSource, resolve_data_path


OVERLAY_PATH = str(SCRIPT_DIR / "gesture_cnn.bit")


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


def report_performance(timings, configured_clocks, csv_path=None,
                       sample_rate=SAMPLE_RATE_HZ, window_size=IN_LENGTH):
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
            writer = csv.DictWriter(output, fieldnames=["sample", "sample_rate_hz", "window_size"] + keys)
            writer.writeheader()
            for sample, row in enumerate(timings, start=1):
                writer.writerow({"sample": sample, "sample_rate_hz": sample_rate,
                                 "window_size": window_size, **row})
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
    balanced = 100.0 * np.mean(np.diag(matrix) / matrix.sum(axis=1).clip(min=1))
    figure, axis = plt.subplots(figsize=(10, 8))
    image = axis.imshow(matrix, interpolation="nearest", cmap="Blues")
    figure.colorbar(image, ax=axis)
    axis.set(
        xticks=np.arange(NUM_CLASSES), yticks=np.arange(NUM_CLASSES),
        xticklabels=class_names, yticklabels=class_names,
        xlabel="Predicted Label", ylabel="True Label",
        title=f"{title_prefix}\nConfusion Matrix (Accuracy: {accuracy:.2f}%, Balanced: {balanced:.2f}%)"
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
    parser.add_argument("--overlay", default=OVERLAY_PATH,
                        help="bitstream path; default: gesture_cnn.bit beside this script")
    parser.add_argument(
        "--data", default=None,
        help="test NPZ beside this script; defaults to the configuration-specific name, then real_gestures_test.npz"
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
    parser.add_argument("--sample-rate", type=int, default=SAMPLE_RATE_HZ,
                        help="expected dataset rate, matching exported weights (default: 50)")
    parser.add_argument("--window-size", type=int, default=IN_LENGTH,
                        help="input samples, matching the compiled bitstream (default: 128)")
    parser.add_argument("--performance-csv", default=None)
    parser.add_argument("--output", default=None)
    args = parser.parse_args()
    if not 1 <= args.sample_rate <= 100:
        parser.error("--sample-rate must be from 1 to 100")
    if args.window_size < 4 or args.window_size % 4:
        parser.error("--window-size must be at least 4 and divisible by 4")
    tag = f"{args.sample_rate}hz_{args.window_size}"
    if args.data is None:
        local = SCRIPT_DIR / f"real_gestures_{tag}_test.npz"
        args.data = str(local if local.is_file() else SCRIPT_DIR / "real_gestures_test.npz")
    if args.overlay != OVERLAY_PATH:
        overlay = Path(args.overlay).expanduser()
        if not overlay.is_absolute() and overlay.parent == Path("."):
            args.overlay = str(SCRIPT_DIR / overlay)
    args.performance_csv = args.performance_csv or str(SCRIPT_DIR / f"fpga_{tag}_performance.csv")
    args.output = args.output or str(SCRIPT_DIR / f"fpga_{tag}_confusion_matrix.png")
    return args


def main():
    args = parse_args()
    if args.warmup < 0:
        raise ValueError("--warmup must be non-negative")
    source = NPZIMUDataSource(resolve_data_path(args.data), args.sample_rate, args.window_size)
    label = (f"{args.sample_rate} Hz | {args.window_size}-sample window "
             f"({args.window_size / args.sample_rate:.2f} s)")
    print(f"Evaluation configuration: {label}")
    for path in (args.output, args.performance_csv):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
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
    with GestureCNNAccelerator(args.overlay, window_size=args.window_size,
                               sample_rate=args.sample_rate) as accelerator:
        matrix, timings = evaluate(accelerator, source, args.warmup,
                                   args.show_predictions)
        report_performance(timings, accelerator.configured_clock_mhz(),
                           args.performance_csv, args.sample_rate, args.window_size)
    accuracy = 100.0 * np.trace(matrix) / matrix.sum()
    mode = "Negative-Control FPGA" if args.shuffle_labels else "FPGA"
    balanced = 100.0 * np.mean(np.diag(matrix) / matrix.sum(axis=1).clip(min=1))
    print(f"Balanced FPGA accuracy: {balanced:.2f}%")
    print(f"Overall FPGA accuracy: {accuracy:.2f}% ({np.trace(matrix)}/{matrix.sum()})")
    print(matrix)
    save_confusion_matrix(matrix, args.output, source.class_names, f"{mode} | {label}")
    metadata = {"sample_rate_hz": args.sample_rate, "window_size": args.window_size,
                "dataset": str(Path(args.data).resolve()), "overlay": str(Path(args.overlay).resolve()),
                "accuracy": accuracy, "balanced_accuracy": balanced,
                "correct": int(np.trace(matrix)), "total": int(matrix.sum()),
                "negative_control": args.shuffle_labels, "warmup": args.warmup,
                "measured_windows": len(timings), "performance_csv": args.performance_csv}
    Path(args.output).with_suffix(".json").write_text(json.dumps(metadata, indent=2) + "\n")


if __name__ == "__main__":
    main()
