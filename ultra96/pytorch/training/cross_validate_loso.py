"""Evaluate unseen-player performance with leave-one-subject-out folds.

Run from the repository root:
    python -m ultra96.pytorch.training.cross_validate_loso --epochs 30
"""

import argparse
import csv
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys

import numpy as np

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from ultra96.real_data.preprocess_for_training import (
    CLASS_NAMES, FILENAME_PATTERN, convert,
)

ULTRA96_DIR = Path(__file__).resolve().parents[2]
# Fixed defaults avoid reusing Optuna settings selected using all four people.
BASELINE_PARAMS = {"lr": 1e-3, "weight_decay": 1e-4, "dropout": 0.3}


def discover_subjects(root):
    recordings = sorted(path for path in root.glob("*/*/*.csv")
                        if FILENAME_PATTERN.fullmatch(path.name))
    subjects = sorted({path.relative_to(root).parts[0] for path in recordings})
    if len(subjects) < 2:
        raise ValueError("Need at least two subjects under input/subject/session/*.csv")
    return subjects


def audit_fold(data_dir, held_out_subject):
    """Fail before training on overlapping recordings or held-out-person leakage."""
    manifest = {}
    recording_sets = {}
    for split in ("train", "val", "test"):
        with np.load(data_dir / f"real_gestures_{split}.npz") as data:
            subjects = set(data["subjects"].tolist())
            filenames = data["filenames"].tolist()
            offsets = data["centre_offsets"]
            if not filenames:
                raise ValueError(f"Empty {split} split")
            if (split == "test" and subjects != {held_out_subject}) or (
                    split != "test" and held_out_subject in subjects):
                raise ValueError(f"Held-out subject leakage in {split}")
            if split != "train" and (
                    np.any(offsets != 0) or len(set(filenames)) != len(filenames)):
                raise ValueError(f"{split} must have one unaugmented window per recording")
            counts = np.bincount(data["y"], minlength=len(CLASS_NAMES))
            if split != "test" and np.any(counts == 0):
                raise ValueError(f"{split} is missing classes: {counts.tolist()}")
            recording_sets[split] = set(filenames)
            manifest[split] = {
                "subjects": sorted(subjects), "windows": len(filenames),
                "recordings": sorted(set(filenames)), "class_counts": counts.tolist(),
            }
    for first, second in (("train", "val"), ("train", "test"), ("val", "test")):
        if recording_sets[first] & recording_sets[second]:
            raise ValueError(f"Recording overlap between {first} and {second}")
    if set(manifest["train"]["subjects"]) != set(manifest["val"]["subjects"]):
        raise ValueError("Each training subject must also have validation recordings")
    return manifest


def metrics_from_confusion(cm):
    """Percent scores; absent true classes are excluded from balanced accuracy."""
    cm = np.asarray(cm, dtype=np.int64)
    support = cm.sum(axis=1)
    predicted = cm.sum(axis=0)
    correct = np.diag(cm)
    recall = np.divide(correct, support, out=np.zeros(len(cm)), where=support > 0)
    precision = np.divide(correct, predicted, out=np.zeros(len(cm)), where=predicted > 0)
    denominator = support + predicted
    f1 = np.divide(2 * correct, denominator, out=np.zeros(len(cm)), where=denominator > 0)
    return {
        "accuracy": float(100 * correct.sum() / cm.sum()),
        "balanced_accuracy": float(100 * recall[support > 0].mean()),
        # Fixed class list: missing classes get zero F1, matching sklearn's
        # labels=range(num_classes), zero_division=0 convention.
        "macro_f1": float(100 * f1.mean()),
        "per_class": [
            {"class": str(name), "support": int(n), "precision": float(100 * p),
             "recall": float(100 * r) if n else None, "f1": float(100 * f)}
            for name, n, p, r, f in zip(CLASS_NAMES, support, precision, recall, f1)
        ],
        "confusion_matrix": cm.tolist(),
    }


def evaluate_fold(checkpoint, data_dir, output_dir, sample_rate, window_size, subject_label=None):
    import torch
    from torch.utils.data import DataLoader
    import matplotlib.pyplot as plt
    from ultra96.pytorch.training.model import Gesture1DCNN
    from ultra96.pytorch.training.train_baseline import NPZIMUDataset

    dataset = NPZIMUDataset(data_dir / "real_gestures_test.npz", sample_rate, window_size)
    metadata = json.loads(checkpoint.with_suffix(".json").read_text())
    if metadata["class_names"] != dataset.class_names:
        raise ValueError("Checkpoint and test class orders differ")
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = Gesture1DCNN(**metadata["model_config"]).to(device)
    model.load_state_dict(torch.load(checkpoint, map_location=device, weights_only=True))
    model.eval()
    predictions = []
    with torch.no_grad():
        for x, _ in DataLoader(dataset, batch_size=32, shuffle=False):
            predictions.extend(model(x.to(device)).argmax(1).cpu().tolist())
    targets = dataset.labels.numpy()
    cm = np.zeros((len(CLASS_NAMES), len(CLASS_NAMES)), dtype=np.int64)
    np.add.at(cm, (targets, predictions), 1)
    metrics = metrics_from_confusion(cm)
    with np.load(data_dir / "real_gestures_test.npz") as data:
        with (output_dir / "predictions.csv").open("w", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["filename", "subject", "true_label", "predicted_label"])
            writer.writerows(zip(data["filenames"], data["subjects"], targets, predictions))
    fig, ax = plt.subplots(figsize=(12, 10))
    image = ax.imshow(cm, cmap="Blues")
    fig.colorbar(image, ax=ax)
    ax.set(xticks=range(len(cm)), yticks=range(len(cm)),
           xticklabels=CLASS_NAMES, yticklabels=CLASS_NAMES,
           xlabel="Predicted gesture", ylabel="True gesture",
           title=f"Unseen subject: {subject_label or output_dir.name} | balanced accuracy {metrics['balanced_accuracy']:.2f}%")
    plt.setp(ax.get_xticklabels(), rotation=60, ha="right")
    for row in range(len(cm)):
        for col in range(len(cm)):
            ax.text(col, row, str(cm[row, col]), ha="center", va="center",
                    color="white" if cm[row, col] > cm.max() / 2 else "black")
    fig.tight_layout()
    fig.savefig(output_dir / "confusion_matrix.png")
    plt.close(fig)
    return metrics


def write_summary(run_dir, folds):
    scores = ("accuracy", "balanced_accuracy", "macro_f1")
    summary = {
        "folds": folds,
        "aggregate": {
            score: {"mean": float(np.mean([fold[score] for fold in folds])),
                    "std": float(np.std([fold[score] for fold in folds], ddof=1))
                    if len(folds) > 1 else 0.0}
            for score in scores
        },
        "std_convention": "sample standard deviation across subjects (ddof=1)",
        "score_units": "percent",
    }
    pooled = np.sum([fold["confusion_matrix"] for fold in folds], axis=0)
    summary["pooled"] = metrics_from_confusion(pooled)
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    with (run_dir / "summary.csv").open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["held_out_subject", *scores])
        for fold in folds:
            writer.writerow([fold["held_out_subject"], *[fold[key] for key in scores]])
        for stat in ("mean", "std"):
            writer.writerow([stat, *[summary["aggregate"][key][stat] for key in scores]])
    return summary


def run(args):
    from ultra96.pytorch.training.train_baseline import REAL_TRAINING_PARAMS, run_pipeline
    from ultra96.pytorch.training.augmentation import make_training_augmentation
    import torch

    torch.set_num_threads(args.threads)
    root = args.input.resolve()
    subjects = discover_subjects(root)
    params = dict(REAL_TRAINING_PARAMS if args.training_settings == "tuned" else BASELINE_PARAMS)
    augmentation = (make_training_augmentation({"kind": args.augmentation or "basic"}).config
                    if args.augment or args.augmentation else None)
    started = datetime.now(timezone(timedelta(hours=8)))
    run_dir = args.output.resolve() / started.strftime("%Y-%m-%d_%H-%M-%S_%f")
    run_dir.mkdir(parents=True, exist_ok=False)
    config = {
        "protocol": "leave-one-subject-out", "started_at": started.isoformat(),
        "input": str(root), "subjects": subjects, "epochs": args.epochs,
        "sample_rate_hz": args.sample_rate, "window_size": args.window_size,
        "seed": 42, "params": params, "training_settings": args.training_settings,
        "prepare_only": args.prepare_only,
        "augmentation": augmentation,
        "architecture": args.architecture,
        "validation": "trials 7-8 in each block of ten from non-test subjects",
        "selection": "best validation balanced accuracy, then validation loss",
        "status": "preparing" if args.prepare_only else "running",
    }
    config_path = run_dir / "protocol.json"
    config_path.write_text(json.dumps(config, indent=2) + "\n")
    print(f"LOSO output: {run_dir}", flush=True)
    folds = []
    for subject in subjects:
        print(f"\n=== Held-out subject: {subject} ===", flush=True)
        fold_dir = run_dir / subject
        data_dir = fold_dir / "data"
        convert(root, data_dir, args.centre_overrides, args.sample_rate,
                args.window_size, held_out_subject=subject)
        manifest = audit_fold(data_dir, subject)
        (fold_dir / "split_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        if args.prepare_only:
            continue
        trained_dir = run_pipeline(
            num_epochs=args.epochs, data_dir=str(data_dir), output_dir=fold_dir / "training",
            sample_rate=args.sample_rate, window_size=args.window_size,
            training_params=params, augmentation=augmentation, architecture=args.architecture,
        )
        training = json.loads((trained_dir / "run.json").read_text())
        checkpoint = trained_dir / training["checkpoint"]
        metrics = evaluate_fold(checkpoint, data_dir, fold_dir, args.sample_rate, args.window_size)
        metrics.update(held_out_subject=subject, best_epoch=training["best_epoch"],
                       checkpoint=str(checkpoint.relative_to(run_dir)))
        (fold_dir / "metrics.json").write_text(json.dumps(metrics, indent=2) + "\n")
        folds.append(metrics)
        summary = write_summary(run_dir, folds)
        print(f"{subject}: accuracy={metrics['accuracy']:.2f}%, "
              f"balanced={metrics['balanced_accuracy']:.2f}%, macro-F1={metrics['macro_f1']:.2f}%",
              flush=True)
    config["status"] = "prepared" if args.prepare_only else "complete"
    config_path.write_text(json.dumps(config, indent=2) + "\n")
    if folds:
        for metric, values in summary["aggregate"].items():
            print(f"{metric}: {values['mean']:.2f} +/- {values['std']:.2f}%", flush=True)
    return run_dir


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=ULTRA96_DIR / "real_data")
    parser.add_argument("--output", type=Path, default=ULTRA96_DIR / "pytorch" / "loso_runs")
    parser.add_argument("--centre-overrides", type=Path)
    parser.add_argument("--epochs", type=int, default=30)
    parser.add_argument("--architecture", choices=("temporal", "legacy"), default="temporal",
                        help="temporal context model (default) or original CNN for comparison")
    parser.add_argument("--sample-rate", type=int, default=50)
    parser.add_argument("--window-size", type=int, default=128)
    parser.add_argument("--threads", type=int, default=4, help="CPU torch threads (default: 4)")
    parser.add_argument("--training-settings", choices=("baseline", "tuned"), default="baseline",
                        help="fixed original defaults or current Optuna-tuned REAL_TRAINING_PARAMS")
    aug = parser.add_mutually_exclusive_group()
    aug.add_argument("--augment", action="store_true",
                        help="apply small amplitude, noise and speed changes to training batches only")
    aug.add_argument("--augmentation", choices=("basic", "imu"),
                     help="training-only preset: basic or shared 3D rotation, smooth time warp and magnitude")
    parser.add_argument("--prepare-only", action="store_true", help="prepare and audit all folds without training")
    args = parser.parse_args()
    if args.epochs < 1 or args.threads < 1 or not 1 <= args.sample_rate <= 100 or args.window_size < 4:
        parser.error("epochs/threads must be positive, sample rate 1-100, window size at least 4")
    return args


if __name__ == "__main__":
    run(parse_args())
