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


def metrics_from_confusion(cm, class_names=CLASS_NAMES):
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
            for name, n, p, r, f in zip(class_names, support, precision, recall, f1)
        ],
        "confusion_matrix": cm.tolist(),
    }


STATE_CLASS_IDS = {"normal": (0, 1, 4, 5, 6, 7, 8, 9, 10), "aiming": (0, 2, 3)}
STATE_EVALUATION_CONTEXT = "Label-supplied state; Neutral tested in both states; assumes correct game state"


def single_head_config(config):
    """Accept historical single-head metadata without restoring the dual model."""
    config = dict(config)
    if config.pop("head_type", "single") != "single":
        raise ValueError("Two-head checkpoints are unsupported; select a single-head checkpoint")
    return config


def state_evaluation_batches(logits, targets, class_names):
    """Return state, masked logits, targets and source indices for clip evaluation.

    This is an evaluation helper, not part of the CNN architecture or training.
    Only the original gesture class order enables masking. Neutral is tested in
    both states; other labels select their eligible state. Mask before softmax.
    """
    import torch
    if tuple(class_names) != tuple(CLASS_NAMES):
        return [("unrestricted", logits, targets, torch.arange(len(targets), device=targets.device))]
    batches = []
    for state, labels in STATE_CLASS_IDS.items():
        ids = torch.tensor(labels, device=logits.device)
        indices = (targets[:, None] == ids[None, :]).any(dim=1).nonzero().flatten()
        if len(indices):
            invalid = torch.ones(logits.shape[1], dtype=torch.bool, device=logits.device)
            invalid[ids] = False
            masked = logits[indices].masked_fill(invalid[None, :], -torch.inf)
            batches.append((state, masked, targets[indices], indices))
    return batches


def state_evaluation_metrics(state_cms, unrestricted_cm, class_names):
    """Main state-conditioned scores plus preserved unrestricted scores."""
    cm = np.sum(list(state_cms.values()), axis=0)
    result = metrics_from_confusion(cm, class_names)
    enabled = tuple(class_names) == tuple(CLASS_NAMES)
    result.update(evaluation_mode="state_masked_single" if enabled else "unrestricted_single",
                  evaluation_context=STATE_EVALUATION_CONTEXT if enabled else "Unrestricted single-head classification",
                  unrestricted=metrics_from_confusion(unrestricted_cm, class_names), states={})
    for state, full_cm in state_cms.items():
        ids = list(STATE_CLASS_IDS[state]) if enabled else list(range(len(class_names)))
        result["states"][state] = metrics_from_confusion(
            full_cm[np.ix_(ids, ids)], [class_names[i] for i in ids])
    return result


def evaluate_fold(checkpoint, data_dir, output_dir, sample_rate, window_size, subject_label=None):
    import torch
    from torch.utils.data import DataLoader
    import matplotlib.pyplot as plt
    from ultra96.pytorch.training.model import Gesture1DCNN
    from ultra96.pytorch.training.train_baseline import NPZIMUDataset

    dataset = NPZIMUDataset(data_dir / "real_gestures_test.npz", sample_rate, window_size)
    metadata = json.loads(checkpoint.with_suffix(".json").read_text())
    if metadata["class_names"] != dataset.class_names or dataset.class_names != CLASS_NAMES.tolist():
        raise ValueError("LOSO requires the original gesture class order in checkpoint and test data")
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = Gesture1DCNN(**single_head_config(metadata["model_config"])).to(device)
    model.load_state_dict(torch.load(checkpoint, map_location=device, weights_only=True))
    model.eval()
    unrestricted_cm = np.zeros((len(CLASS_NAMES), len(CLASS_NAMES)), dtype=np.int64)
    state_cms, rows = {}, []
    with np.load(data_dir / "real_gestures_test.npz") as data:
        filenames, subjects = data["filenames"].tolist(), data["subjects"].tolist()
    offset = 0
    with torch.no_grad():
        for x, y in DataLoader(dataset, batch_size=32, shuffle=False):
            logits = model(x.to(device))
            raw = logits.argmax(1).cpu().numpy()
            np.add.at(unrestricted_cm, (y.numpy(), raw), 1)
            for state, masked, targets, indices in state_evaluation_batches(logits, y.to(device), dataset.class_names):
                targets, predictions = targets.cpu().numpy(), masked.argmax(1).cpu().numpy()
                state_cm = state_cms.setdefault(state, np.zeros_like(unrestricted_cm))
                np.add.at(state_cm, (targets, predictions), 1)
                rows.extend((filenames[offset+i], subjects[offset+i], int(target), int(prediction), state, int(raw[i]))
                            for i, target, prediction in zip(indices.cpu().tolist(), targets, predictions))
            offset += len(y)
    metrics = state_evaluation_metrics(state_cms, unrestricted_cm, dataset.class_names)
    cm = np.asarray(metrics["confusion_matrix"])
    with (output_dir / "predictions.csv").open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["filename", "subject", "true_label", "predicted_label", "state", "unrestricted_prediction"])
        writer.writerows(rows)
    fig, ax = plt.subplots(figsize=(12, 10))
    image = ax.imshow(cm, cmap="Blues")
    fig.colorbar(image, ax=ax)
    ax.set(xticks=range(len(cm)), yticks=range(len(cm)),
           xticklabels=CLASS_NAMES, yticklabels=CLASS_NAMES,
           xlabel="Predicted gesture", ylabel="True gesture",
           title=f"Unseen subject: {subject_label or output_dir.name} | state-masked balanced {metrics['balanced_accuracy']:.2f}%\n"
                 + metrics["evaluation_context"])
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

    def combine(items, names=CLASS_NAMES):
        return {"aggregate": {
            score: {"mean": float(np.mean([item[score] for item in items])),
                    "std": float(np.std([item[score] for item in items], ddof=1)) if len(items) > 1 else 0.0}
            for score in scores},
            "pooled": metrics_from_confusion(np.sum([item["confusion_matrix"] for item in items], axis=0), names)}

    summary = {"folds": folds, **combine(folds),
               "std_convention": "sample standard deviation across subjects (ddof=1)",
               "score_units": "percent", "evaluation_mode": folds[0].get("evaluation_mode", "historical"),
               "evaluation_context": folds[0].get("evaluation_context"), "states": {}}
    if all("unrestricted" in fold for fold in folds):
        summary["unrestricted"] = combine([fold["unrestricted"] for fold in folds])
    for state, ids in STATE_CLASS_IDS.items():
        if all(state in fold.get("states", {}) for fold in folds):
            summary["states"][state] = combine([fold["states"][state] for fold in folds], [CLASS_NAMES[i] for i in ids])
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    with (run_dir / "summary.csv").open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["held_out_subject", *scores, "normal_balanced_accuracy", "aiming_balanced_accuracy", "unrestricted_balanced_accuracy"])
        for fold in folds:
            writer.writerow([fold["held_out_subject"], *[fold[key] for key in scores],
                             *[fold.get("states", {}).get(state, {}).get("balanced_accuracy", "") for state in STATE_CLASS_IDS],
                             fold.get("unrestricted", {}).get("balanced_accuracy", "")])
        for stat in ("mean", "std"):
            writer.writerow([stat, *[summary["aggregate"][key][stat] for key in scores],
                             *[summary["states"].get(state, {}).get("aggregate", {}).get("balanced_accuracy", {}).get(stat, "")
                               for state in STATE_CLASS_IDS],
                             summary.get("unrestricted", {}).get("aggregate", {}).get("balanced_accuracy", {}).get(stat, "")])
    return summary


def reevaluate_run(run_dir):
    """Refresh completed single-head LOSO reports without retraining."""
    run_dir = Path(run_dir).resolve()
    protocol = json.loads((run_dir / "protocol.json").read_text())
    previous = json.loads((run_dir / "summary.json").read_text())
    if protocol.get("status") != "complete" or not previous.get("folds"):
        raise ValueError("Re-evaluation requires a completed LOSO run")
    prepared = []
    for fold in previous["folds"]:
        checkpoint = run_dir / Path(fold["checkpoint"].replace("\\", "/"))
        folder = run_dir / fold["held_out_subject"]
        if not checkpoint.is_file() or not (folder / "data/real_gestures_test.npz").is_file():
            raise ValueError(f"Missing checkpoint or test data for {folder.name}")
        single_head_config(json.loads(checkpoint.with_suffix(".json").read_text())["model_config"])
        prepared.append((fold, checkpoint, folder))
    folds = []
    for old, checkpoint, folder in prepared:
        metrics = evaluate_fold(checkpoint, folder / "data", folder, protocol["sample_rate_hz"], protocol["window_size"])
        metrics.update({key: old[key] for key in ("held_out_subject", "best_epoch", "checkpoint") if key in old})
        (folder / "metrics.json").write_text(json.dumps(metrics, indent=2) + "\n")
        folds.append(metrics)
        print(f"{folder.name}: masked={metrics['balanced_accuracy']:.2f}%, unrestricted={metrics['unrestricted']['balanced_accuracy']:.2f}%", flush=True)
    summary = write_summary(run_dir, folds)
    protocol.update(evaluation_mode="state_masked_single", evaluation_context=STATE_EVALUATION_CONTEXT,
                    evaluation_refreshed_at=datetime.now(timezone(timedelta(hours=8))).isoformat())
    (run_dir / "protocol.json").write_text(json.dumps(protocol, indent=2) + "\n")
    print(f"Mean state-masked balanced accuracy: {summary['aggregate']['balanced_accuracy']['mean']:.2f}%")
    return run_dir

def run(args):
    from ultra96.pytorch.training.train_baseline import REAL_TRAINING_PARAMS, run_pipeline
    from ultra96.pytorch.training.augmentation import make_training_augmentation
    import torch

    torch.set_num_threads(args.threads)
    if args.reevaluate_run is not None:
        return reevaluate_run(args.reevaluate_run)
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
        "evaluation_mode": "state_masked_single", "evaluation_context": STATE_EVALUATION_CONTEXT,
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
    parser.add_argument("--reevaluate-run", type=Path,
                        help="Refresh saved single-head LOSO reports without retraining")
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
