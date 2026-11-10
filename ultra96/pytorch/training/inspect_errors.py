"""Plot test errors and correctly classified references for comparison."""

import argparse
import csv
import json
import shutil
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import torch

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from ultra96.pytorch.training.model import Gesture1DCNN
from ultra96.pytorch.training.cross_validate_loso import STATE_CLASS_IDS, single_head_config, state_evaluation_batches
from ultra96.pytorch.training.train_baseline import resolve_software_checkpoint, SAMPLE_RATE_HZ as DEFAULT_SAMPLE_RATE_HZ
from ultra96.real_data.preprocess_for_training import (
    load_csv, motion_centre, resample_signal, SAMPLE_RATE_HZ,
)

ROOT = Path(__file__).resolve().parents[2]  # ultra96/


def select_reference(index, correct, labels, subjects, sessions, states=None):
    """Prefer the same session; never substitute another person's gesture."""
    candidates = [int(j) for j in correct
                  if labels[j] == labels[index] and subjects[j] == subjects[index]
                  and (states is None or states[j] == states[index])]
    same_session = [j for j in candidates if sessions[j] == sessions[index]]
    return next(iter(same_session or candidates), None)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=ROOT / "real_data")
    parser.add_argument("--data", type=Path, default=ROOT / "real_data/processed_50hz_128/real_gestures_test.npz")
    parser.add_argument("--checkpoint", type=Path, default=None,
                        help="default: latest checkpoint matching dataset metadata")
    parser.add_argument("--output", type=Path, default=ROOT / "pytorch/error_inspection_50hz_128",
                        help="Output directory; deleted and recreated on each run")
    args = parser.parse_args()
    with np.load(args.data) as data:
        windows = data["X"].copy()
        labels = data["y"].copy()
        names = data["class_names"].tolist()
        filenames = data["filenames"].tolist()
        offsets = data["centre_offsets"].copy()
        centres = data["window_centres"].copy() if "window_centres" in data else None
        subjects = data["subjects"].tolist()
        sessions = data["sessions"].tolist()
        sample_rate = int(data["sample_rate_hz"].item()) if "sample_rate_hz" in data else DEFAULT_SAMPLE_RATE_HZ
        window_size = int(data["window_size"].item()) if "window_size" in data else windows.shape[-1]
        source_rate = int(data["source_sample_rate_hz"].item()) if "source_sample_rate_hz" in data else SAMPLE_RATE_HZ
    if windows.ndim != 3 or windows.shape[1:] != (6, window_size):
        raise ValueError(f"Expected dataset X shape [N, 6, {window_size}], got {windows.shape}")
    if source_rate != SAMPLE_RATE_HZ or not 0 < sample_rate <= source_rate:
        raise ValueError("Expected 100 Hz source recordings and an output rate from 1 to 100 Hz")
    run_label = f"{sample_rate} Hz | {window_size}-sample window ({window_size / sample_rate:.2f} s)"
    print(f"Inspecting: {run_label}")
    config = {"num_classes": len(names)}
    args.checkpoint = args.checkpoint or resolve_software_checkpoint("real", sample_rate, window_size)
    config_path = args.checkpoint.with_suffix(".json")
    if config_path.is_file():
        metadata = json.loads(config_path.read_text())
        if metadata["class_names"] != names:
            raise ValueError("Checkpoint and dataset have different class orders")
        for key, expected in (("sample_rate_hz", sample_rate), ("window_size", window_size)):
            if key in metadata and metadata[key] != expected:
                raise ValueError(f"Checkpoint {key} does not match dataset")
        config = metadata["model_config"]
    model = Gesture1DCNN(**single_head_config(config))
    model.load_state_dict(torch.load(args.checkpoint, map_location="cpu", weights_only=True))
    model.eval()
    with torch.no_grad():
        outputs = model(torch.from_numpy(windows).float())
        batches = state_evaluation_batches(outputs, torch.from_numpy(labels).long(), names)
        logits = torch.cat([masked for _, masked, _, _ in batches]).numpy()
        probabilities = torch.cat([masked.softmax(1) for _, masked, _, _ in batches]).numpy()
    indices = [i for _, _, _, selected in batches for i in selected.tolist()]
    states = [state for state, _, targets, _ in batches for _ in targets]
    labels, offsets = labels[indices], offsets[indices]
    centres = centres[indices] if centres is not None else None
    filenames, subjects, sessions = ([values[i] for i in indices] for values in (filenames, subjects, sessions))
    print("State-conditioned clip evaluation; Neutral tested in both states for the original gesture dataset.")
    predictions = probabilities.argmax(axis=1)
    if args.output.exists():
        shutil.rmtree(args.output)
    args.output.mkdir(parents=True)
    errors = np.flatnonzero(predictions != labels)
    correct = np.flatnonzero(predictions == labels)
    # Generate only references paired with errors, from the same person.
    references = set()
    comparisons = {}
    for i in errors:
        reference = select_reference(i, correct, labels, subjects, sessions, states)
        comparisons[int(i)] = reference
        if reference is not None:
            references.add(reference)
        else:
            print(f"No correctly classified test reference for {names[labels[i]]} "
                  f"from {subjects[i]} (error: {filenames[i]})")

    def plot_name(i):
        kind = "correct" if predictions[i] == labels[i] else "error"
        return f"{kind}_{i:03d}_{Path(filenames[i]).stem}.png"

    print(f"{len(errors)} errors / {len(labels)} supervised test tasks")
    with (args.output / "errors.csv").open("w", newline="") as handle, (args.output / "correct.csv").open("w", newline="") as correct_handle:
        error_writer = csv.writer(handle)
        correct_writer = csv.writer(correct_handle)
        columns = ["filename", "true", "predicted", "softmax_score", "plot", "state"]
        error_writer.writerow(columns + ["correct_reference_plot", "reference_same_session", "reference_status"])
        correct_writer.writerow(columns)
        for i in list(errors) + sorted(references):
            path = args.data_root / filenames[i]
            signal = load_csv(path)
            if centres is not None:
                centre = int(centres[i])
            else:
                source_centre = len(signal) // 2 if labels[i] == 0 else motion_centre(signal)
                centre = round(source_centre * sample_rate / source_rate) + int(offsets[i])
            signal = resample_signal(signal, sample_rate)
            start = centre - window_size // 2
            end = start + window_size
            time = np.arange(len(signal)) / sample_rate
            fig = plt.figure(figsize=(12, 9), layout="constrained")
            grid = fig.add_gridspec(3, 1, height_ratios=(1, 1, 1.2))
            axes = [fig.add_subplot(grid[0])]
            axes.append(fig.add_subplot(grid[1], sharex=axes[0]))
            logit_ax = fig.add_subplot(grid[2])
            for ax, channels, title in zip(axes, ((0, 1, 2), (3, 4, 5)), ("Acceleration / sensor range", "Gyroscope / sensor range")):
                for channel in channels:
                    ax.plot(time, signal[:, channel], label=("ax", "ay", "az", "gx", "gy", "gz")[channel])
                ax.axvspan(start / sample_rate, end / sample_rate, color="orange", alpha=0.2,
                           label=f"Selected {window_size / sample_rate:.2f} s window")
                ax.axvline(centre / sample_rate, color="black", linestyle="--", label="Selected centre")
                ax.set_ylabel(title)
                ax.legend(loc="upper right", fontsize=8)
                ax.grid(alpha=0.2)
            axes[-1].set_xlabel(f"Seconds from recording start ({sample_rate} Hz)")
            ids = list(STATE_CLASS_IDS[states[i]]) if states[i] in STATE_CLASS_IDS else list(range(len(names)))
            colors = ["tab:orange" if j == predictions[i] else
                      "tab:green" if j == labels[i] else "tab:blue"
                      for j in ids]
            bars = logit_ax.bar([names[j] for j in ids], logits[i, ids], color=colors)
            logit_ax.bar_label(bars, fmt="%.3f", padding=3, fontsize=8)
            logit_ax.axhline(0, color="black", linewidth=0.7)
            logit_ax.set_ylabel("Raw logit (before softmax)")
            logit_ax.set_title(f"{states[i].title()} state logits — orange: predicted, green: true (if different)")
            logit_ax.tick_params(axis="x", labelrotation=30)
            logit_ax.margins(y=0.2)
            logit_ax.grid(axis="y", alpha=0.2)
            padding = max(0, -start) + max(0, end - len(signal))
            fig.suptitle(f"{filenames[i]} | {run_label}\nTrue: {names[labels[i]]} | Predicted: {names[predictions[i]]} | Edge padding: {padding} samples")
            plot = args.output / plot_name(i)
            fig.savefig(plot)
            plt.close(fig)
            row = [filenames[i], names[labels[i]], names[predictions[i]], float(probabilities[i, predictions[i]]), plot.name, states[i]]
            if predictions[i] == labels[i]:
                correct_writer.writerow(row)
            else:
                reference = comparisons[int(i)]
                error_writer.writerow(row + [
                    plot_name(reference) if reference is not None else "",
                    sessions[reference] == sessions[i] if reference is not None else "",
                    "matched_same_person" if reference is not None else "no_correct_same_person_example",
                ])
            print(f"{filenames[i]}: {names[labels[i]]} -> {names[predictions[i]]}")
    print(f"Report and plots: {args.output}")
    print(f"Generated {len(references)} correctly classified reference plots")


if __name__ == "__main__":
    main()
