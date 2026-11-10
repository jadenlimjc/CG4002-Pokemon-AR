"""FPGA evaluation: state-masked/unrestricted accuracy and inference performance."""

import argparse
import csv
import os
from pathlib import Path
import sys

import numpy as np

SCRIPT_DIR = Path(__file__).resolve().parent

if __package__:
    from ..deployment.cnn_pynq_ultra96 import (
        GestureCNNAccelerator, NUM_CLASSES, IN_LENGTH, SAMPLE_RATE_HZ, OVERLAY_PATH as DRIVER_OVERLAY_PATH,
    )
    from .evaluation_data import NPZIMUDataSource, resolve_data_path
else:
    # A board bundle can contain all three scripts in the same directory.
    if (SCRIPT_DIR / "cnn_pynq_ultra96.py").is_file():
        from cnn_pynq_ultra96 import (
            GestureCNNAccelerator, NUM_CLASSES, IN_LENGTH, SAMPLE_RATE_HZ, OVERLAY_PATH as DRIVER_OVERLAY_PATH,
        )
    else:
        # Also support the repository's sibling deployment/utility layout.
        sys.path.insert(0, str(SCRIPT_DIR.parent))
        from deployment.cnn_pynq_ultra96 import (
            GestureCNNAccelerator, NUM_CLASSES, IN_LENGTH, SAMPLE_RATE_HZ, OVERLAY_PATH as DRIVER_OVERLAY_PATH,
        )
    from evaluation_data import NPZIMUDataSource, resolve_data_path


OVERLAY_PATH = (str(SCRIPT_DIR / "gesture_cnn.bit")
                if (SCRIPT_DIR / "gesture_cnn.bit").is_file() else DRIVER_OVERLAY_PATH)


# Keep the board bundle independent of PyTorch and the training source tree.
# These are the original NPZ class IDs, not additional hardware outputs.
GESTURE_CLASS_NAMES = (
    "Neutral", "Aim", "Stop Aim", "Throw", "Punch", "Downward Swipe", "Guard",
    "Flee / U-turn", "Switch Pokemon / Back-pocket reach",
    "Use Item / Front-pocket reach", "Uppercut",
)
STATE_CLASS_IDS = {"normal": (0, 1, 4, 5, 6, 7, 8, 9, 10), "aiming": (0, 2, 3)}


def classification_metrics(matrix, class_names):
    """Percent scores, matching software evaluation; absent recalls are excluded."""
    support, predicted = matrix.sum(1), matrix.sum(0)
    correct = np.diag(matrix)
    recall = np.divide(correct, support, out=np.zeros(len(matrix)), where=support > 0)
    precision = np.divide(correct, predicted, out=np.zeros(len(matrix)), where=predicted > 0)
    denominator = support + predicted
    f1 = np.divide(2 * correct, denominator, out=np.zeros(len(matrix)), where=denominator > 0)
    total = int(matrix.sum())
    return {
        "accuracy": float(100 * correct.sum() / total) if total else None,
        "balanced_accuracy": float(100 * recall[support > 0].mean()) if total else None,
        "macro_f1": float(100 * f1.mean()) if total else None,
        "correct": int(correct.sum()), "total": total,
        "per_class": [
            {"class": str(name), "support": int(n), "precision": float(100 * p),
             "recall": float(100 * r) if n else None, "f1": float(100 * f)}
            for name, n, p, r, f in zip(class_names, support, precision, recall, f1)
        ],
        "confusion_matrix": matrix.tolist(),
    }


def evaluate(accelerator, data_source, warmup=10, show_predictions=False, *, state_mask=False):
    """Infer once per source window; score both restrictions from the same logits.

    Returns (evaluation report, hardware timings). CPU masking is outside the
    driver's timed interval. State is supplied by labels for clip evaluation;
    this does not simulate live state tracking or action acceptance.
    """
    if warmup < 0:
        raise ValueError("warmup must be non-negative")
    names = data_source.class_names
    if state_mask and tuple(names) != GESTURE_CLASS_NAMES:
        raise ValueError("State masking requires the original 11 gesture labels in their original order")
    state_masking = state_mask
    matrix = np.zeros((NUM_CLASSES, NUM_CLASSES), dtype=np.int64)
    state_matrices = {state: np.zeros_like(matrix) for state in STATE_CLASS_IDS} if state_masking else {}
    timings = []
    count = 0
    for count, (window, target) in enumerate(data_source, start=1):
        target = int(target)
        if not 0 <= target < NUM_CLASSES:
            raise ValueError(f"Invalid label {target} at sample {count}")
        logits, timing = accelerator.predict_logits_timed(window)
        logits = np.asarray(logits)
        if logits.shape != (NUM_CLASSES,) or not np.isfinite(logits).all():
            raise ValueError(f"Sample {count}: expected {NUM_CLASSES} finite FPGA logits")
        prediction = int(np.argmax(logits))
        if count > warmup:
            timings.append(timing.as_dict())
        matrix[target, prediction] += 1
        state_predictions = {}
        for state, ids in STATE_CLASS_IDS.items() if state_masking else ():
            if target in ids:
                # Restrict before argmax, rather than rejecting an invalid winner.
                selected = int(ids[int(np.argmax(logits[list(ids)]))])
                state_matrices[state][target, selected] += 1
                state_predictions[state] = selected
        if show_predictions:
            logit_text = ", ".join(f"{i}:{float(value):.6f}" for i, value in enumerate(logits))
            print(f"Sample {count:3d}: true={target}, unrestricted={prediction}, "
                  f"state_masked={state_predictions}, logits=[{logit_text}]", flush=True)
        else:
            print(f"\rProcessed {count} samples; latest true={target}, unrestricted={prediction}", end="", flush=True)
    if not show_predictions:
        print()
    if count == 0:
        raise ValueError("The data source did not produce any samples")
    if not timings:
        raise ValueError("Samples must exceed --warmup to produce benchmark data")
    primary = np.sum(list(state_matrices.values()), axis=0) if state_masking else matrix
    report = {
        **classification_metrics(primary, names),
        "evaluation_mode": "state_masked_single" if state_masking else "unrestricted_single",
        "state_masking_enabled": state_masking, "source_windows": count,
        "evaluation_context": ("Label-supplied state; Neutral tested in both states; assumes correct game state"
                               if state_masking else "Unrestricted single-head classification"),
        "unrestricted": classification_metrics(matrix, names), "states": {},
    }
    for state, full_matrix in state_matrices.items():
        ids = list(STATE_CLASS_IDS[state])
        report["states"][state] = classification_metrics(full_matrix[np.ix_(ids, ids)], [names[i] for i in ids])
    return report, timings

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


def save_confusion_matrix(matrix, path, class_names, title_prefix="FPGA", unrestricted_matrix=None, state_results=None):
    """Plot software-compatible state panels; keep both evaluations in one CSV."""
    panels = [("State-masked", matrix), ("Unrestricted", unrestricted_matrix)] if unrestricted_matrix is not None else [("Unrestricted", matrix)]
    csv_path = os.path.splitext(path)[0] + ".csv"
    with open(csv_path, "w", newline="") as output:
        writer = csv.writer(output)
        writer.writerow(["evaluation", "true_class", *class_names])
        for name, values in panels:
            for label, row in zip(class_names, values):
                writer.writerow([name, label, *row.tolist()])
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print(f"matplotlib is unavailable; saved confusion matrices to {csv_path}")
        return

    plot_panels = []
    if state_results:
        for state, metrics in state_results.items():
            names = [class_names[i] for i in STATE_CLASS_IDS[state]]
            plot_panels.append((f"{state.title()} state", np.asarray(metrics["confusion_matrix"]), names))
    else:
        plot_panels = [(name, values, class_names) for name, values in panels]
    figure, axes = plt.subplots(1, len(plot_panels), figsize=(9 * len(plot_panels), 8), squeeze=False)
    for axis, (name, values, names) in zip(axes[0], plot_panels):
        metrics = classification_metrics(values, names)
        accuracy, balanced = metrics["accuracy"], metrics["balanced_accuracy"]
        image = axis.imshow(values, interpolation="nearest", cmap="Blues", aspect="auto", vmin=0)
        figure.colorbar(image, ax=axis)
        panel_title = (f"{name} | accuracy {accuracy:.2f}% | balanced {balanced:.2f}%"
                       if metrics["total"] else f"{name} | no eligible test windows")
        axis.set(
            xticks=np.arange(len(names)), yticks=np.arange(len(names)),
            xticklabels=names, yticklabels=names,
            xlabel="Predicted Label", ylabel="True Label", title=panel_title,
        )
        plt.setp(axis.get_xticklabels(), rotation=90, ha="center")
        threshold = values.max() / 2.0
        for row in range(len(names)):
            for column in range(len(names)):
                axis.text(column, row, str(values[row, column]), ha="center", va="center",
                          color="white" if values[row, column] > threshold else "black")
    figure.suptitle(title_prefix)
    figure.tight_layout()
    figure.savefig(path, bbox_inches="tight")
    plt.close(figure)
    print(f"Saved confusion matrices to {path} and {csv_path}")

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
    parser.add_argument("--state-mask", action="store_true",
                        help="enable state-masked evaluation and normal/aiming PNG panels (default: unrestricted)")
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
    if not 16 <= args.window_size < 65536 or args.window_size % 4:
        parser.error("--window-size must be 16..65532 and divisible by 4 for the temporal CNN")
    tag = f"{args.sample_rate}hz_{args.window_size}"
    if args.data is None:
        local = SCRIPT_DIR / f"real_gestures_{tag}_test.npz"
        candidates = (local, SCRIPT_DIR / "real_gestures_test.npz",
                      Path(DRIVER_OVERLAY_PATH).parent / "real_gestures_test.npz")
        args.data = str(next((path for path in candidates if path.is_file()), candidates[1]))
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
    if args.state_mask and tuple(source.class_names) != GESTURE_CLASS_NAMES:
        raise ValueError("State masking requires the original 11 gesture labels in their original order")
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
        results, timings = evaluate(accelerator, source, args.warmup,
                                   args.show_predictions, state_mask=args.state_mask)
        report_performance(timings, accelerator.configured_clock_mhz(),
                           args.performance_csv, args.sample_rate, args.window_size)
    mode = "Negative-Control FPGA" if args.shuffle_labels else "FPGA"
    print(f"\n{results['evaluation_context']}")
    if args.shuffle_labels and results["state_masking_enabled"]:
        print("Negative control: masks also use SHUFFLED scoring labels. "
              "Use unrestricted results for the 11-class chance-level check.")
    print(f"Primary ({results['evaluation_mode']}) accuracy: {results['accuracy']:.2f}% "
          f"({results['correct']}/{results['total']} evaluation tasks; {results['source_windows']} FPGA windows)")
    print(f"Primary balanced accuracy: {results['balanced_accuracy']:.2f}%")
    print(f"Unrestricted accuracy: {results['unrestricted']['accuracy']:.2f}% | "
          f"balanced: {results['unrestricted']['balanced_accuracy']:.2f}%")
    for state, metrics in results["states"].items():
        if metrics["total"]:
            print(f"{state.title()} state: accuracy={metrics['accuracy']:.2f}% | "
                  f"balanced={metrics['balanced_accuracy']:.2f}% | tasks={metrics['total']}")
        else:
            print(f"{state.title()} state: no eligible test windows")
    title = f"{mode} | {label} | {results['evaluation_mode']}"
    if results["state_masking_enabled"]:
        title += "\nLabel-supplied state; Neutral tested in both states; assumes correct game state"
    save_confusion_matrix(
        np.asarray(results["confusion_matrix"]), args.output, source.class_names, title,
        unrestricted_matrix=(np.asarray(results["unrestricted"]["confusion_matrix"])
                             if results["state_masking_enabled"] else None),
        state_results=results["states"],
    )



if __name__ == "__main__":
    main()
