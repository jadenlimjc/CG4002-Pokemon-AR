"""Plot test errors and correctly classified references for comparison."""

import argparse
import csv
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

ROOT = Path(__file__).resolve().parents[2]  # ultra96/
sys.path.insert(0, str(ROOT / "real_data"))
from preprocess_real_gestures import load_csv, motion_centre, WINDOW_SIZE, SAMPLE_RATE_HZ


def select_reference(index, correct, labels, subjects, sessions):
    """Prefer the same session; never substitute another person's gesture."""
    candidates = [int(j) for j in correct
                  if labels[j] == labels[index] and subjects[j] == subjects[index]]
    same_session = [j for j in candidates if sessions[j] == sessions[index]]
    return next(iter(same_session or candidates), None)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=ROOT / "real_data")
    parser.add_argument("--data", type=Path, default=ROOT / "real_data/processed/real_gestures_test.npz")
    parser.add_argument("--checkpoint", type=Path, default=ROOT / "pytorch/saved_checkpoints/gesture_1dcnn_real_100hz_256_best.pth")
    parser.add_argument("--output", type=Path, default=ROOT / "pytorch/error_inspection")
    args = parser.parse_args()
    with np.load(args.data) as data:
        windows = data["X"].copy()
        labels = data["y"].copy()
        names = data["class_names"].tolist()
        filenames = data["filenames"].tolist()
        offsets = data["centre_offsets"].copy()
        subjects = data["subjects"].tolist()
        sessions = data["sessions"].tolist()
    model = Gesture1DCNN(num_classes=len(names))
    model.load_state_dict(torch.load(args.checkpoint, map_location="cpu", weights_only=True))
    model.eval()
    with torch.no_grad():
        probabilities = model(torch.from_numpy(windows).float()).softmax(dim=1).numpy()
    predictions = probabilities.argmax(axis=1)
    args.output.mkdir(parents=True, exist_ok=True)
    errors = np.flatnonzero(predictions != labels)
    correct = np.flatnonzero(predictions == labels)
    # Generate only references paired with errors, from the same person.
    references = set()
    comparisons = {}
    for i in errors:
        reference = select_reference(i, correct, labels, subjects, sessions)
        comparisons[int(i)] = reference
        if reference is not None:
            references.add(reference)
        else:
            print(f"No correctly classified test reference for {names[labels[i]]} "
                  f"from {subjects[i]} (error: {filenames[i]})")

    def plot_name(i):
        kind = "correct" if predictions[i] == labels[i] else "error"
        return f"{kind}_{i:03d}_{Path(filenames[i]).stem}.png"

    print(f"{len(errors)} errors / {len(labels)} test windows")
    with (args.output / "errors.csv").open("w", newline="") as handle, (args.output / "correct.csv").open("w", newline="") as correct_handle:
        error_writer = csv.writer(handle)
        correct_writer = csv.writer(correct_handle)
        columns = ["filename", "true", "predicted", "softmax_score", "plot"]
        error_writer.writerow(columns + ["correct_reference_plot", "reference_same_session", "reference_status"])
        correct_writer.writerow(columns)
        for i in list(errors) + sorted(references):
            path = args.data_root / filenames[i]
            signal = load_csv(path)
            centre = (len(signal) // 2 if labels[i] == 0 else motion_centre(signal)) + int(offsets[i])
            start = centre - WINDOW_SIZE // 2
            end = start + WINDOW_SIZE
            time = np.arange(len(signal)) / SAMPLE_RATE_HZ
            fig, axes = plt.subplots(2, 1, figsize=(12, 6), sharex=True)
            for ax, channels, title in zip(axes, ((0, 1, 2), (3, 4, 5)), ("Acceleration / sensor range", "Gyroscope / sensor range")):
                for channel in channels:
                    ax.plot(time, signal[:, channel], label=("ax", "ay", "az", "gx", "gy", "gz")[channel])
                ax.axvspan(start / SAMPLE_RATE_HZ, end / SAMPLE_RATE_HZ, color="orange", alpha=0.2, label="Selected 2.56 s window")
                ax.axvline(centre / SAMPLE_RATE_HZ, color="black", linestyle="--", label="Selected centre")
                ax.set_ylabel(title)
                ax.legend(loc="upper right", fontsize=8)
                ax.grid(alpha=0.2)
            axes[-1].set_xlabel("Seconds from recording start (assumed 100 Hz)")
            padding = max(0, -start) + max(0, end - len(signal))
            fig.suptitle(f"{filenames[i]}\nTrue: {names[labels[i]]} | Predicted: {names[predictions[i]]} | Edge padding: {padding} samples")
            fig.tight_layout()
            plot = args.output / plot_name(i)
            fig.savefig(plot)
            plt.close(fig)
            row = [filenames[i], names[labels[i]], names[predictions[i]], float(probabilities[i, predictions[i]]), plot.name]
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
