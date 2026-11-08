"""Nested subject validation for four fixed dropout/weight-decay settings.

python -m ultra96.pytorch.training.regularize_loso --epochs 30
"""

import argparse
import csv
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import torch
from torch.utils.data import DataLoader, Dataset

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from ultra96.pytorch.training.cross_validate_loso import (
    ULTRA96_DIR, discover_subjects, evaluate_fold, write_summary,
)
from ultra96.pytorch.training.model import Gesture1DCNN
from ultra96.pytorch.training.train_baseline import REAL_TRAINING_PARAMS, set_seed
from ultra96.pytorch.training.tune_optuna import fit, model_config
from ultra96.real_data.preprocess_for_training import CLASS_NAMES, convert


def save_json(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n")


def candidates():
    current = dict(REAL_TRAINING_PARAMS)
    return {
        "current": current,
        "dropout": {**current, "dropout": 0.4},
        "weight_decay": {**current, "weight_decay": 0.001},
        "both": {**current, "dropout": 0.4, "weight_decay": 0.001},
    }


class SubjectWindows(Dataset):
    def __init__(self, source, subjects):
        mask = np.isin(source["subjects"], subjects)
        self.data = torch.from_numpy(source["X"][mask].copy())
        self.labels = torch.from_numpy(source["y"][mask].copy()).long()
        self.class_names = source["class_names"].tolist()
        self.subjects = sorted(set(source["subjects"][mask].tolist()))
        self.filenames = sorted(set(source["filenames"][mask].tolist()))
        if self.subjects != sorted(subjects) or not len(self.labels):
            raise ValueError(f"Missing subject data for {subjects}")
        if torch.any(torch.bincount(self.labels, minlength=len(CLASS_NAMES)) == 0):
            raise ValueError(f"Missing gesture classes for {subjects}")

    def __len__(self):
        return len(self.labels)

    def __getitem__(self, index):
        return self.data[index], self.labels[index]

    def manifest(self):
        return {"subjects": self.subjects, "windows": len(self), "recordings": self.filenames}


def audit_subject_split(train, val, outer):
    if (set(train.subjects) & set(val.subjects) or outer in train.subjects
            or outer in val.subjects or set(train.filenames) & set(val.filenames)):
        raise ValueError("Subject or recording leakage in inner split")


def summarize_inner(results):
    return {
        name: {
            "mean_balanced_accuracy": float(np.mean([r["balanced_accuracy"] for r in rows])),
            "mean_val_loss": float(np.mean([r["val_loss"] for r in rows])),
            "refit_epochs": max(1, int(np.floor(np.median([r["epoch"] for r in rows]) + 0.5))),
            "runs": rows,
        }
        for name, rows in results.items()
    }


def select_setting(summary, min_gain=1.0):
    # Fixed practical threshold, not a statistical significance test. Prefer
    # current on ties and small improvements; never inspect outer predictions.
    winner = min(summary, key=lambda name: (
        -summary[name]["mean_balanced_accuracy"], summary[name]["mean_val_loss"], name != "current"))
    gain = summary[winner]["mean_balanced_accuracy"] - summary["current"]["mean_balanced_accuracy"]
    return winner if gain >= min_gain else "current"


def train_fixed(train, params, epochs, destination, device, metadata):
    """Refit for a duration fixed before outer test evaluation; no test selection."""
    set_seed(42)
    config = model_config(params, len(CLASS_NAMES))
    model = Gesture1DCNN(**config).to(device)
    counts = torch.bincount(train.labels, minlength=len(CLASS_NAMES)).float()
    weights = (len(train) / (len(CLASS_NAMES) * counts)).to(device)
    criterion = torch.nn.CrossEntropyLoss(weight=weights)
    optimizer = torch.optim.Adam(model.parameters(), lr=params["lr"], weight_decay=params["weight_decay"])
    loader = DataLoader(train, batch_size=32, shuffle=True)
    history = []
    for epoch in range(1, epochs + 1):
        model.train()
        loss_sum, correct = 0.0, 0
        for x, y in loader:
            x, y = x.to(device), y.to(device)
            optimizer.zero_grad()
            logits = model(x)
            loss = criterion(logits, y)
            loss.backward()
            optimizer.step()
            loss_sum += loss.item() * len(y)
            correct += (logits.argmax(1) == y).sum().item()
        history.append({"epoch": epoch, "loss": loss_sum / len(train),
                        "accuracy": 100 * correct / len(train)})
    destination.parent.mkdir(parents=True, exist_ok=True)
    torch.save(model.state_dict(), destination)
    save_json(destination.with_suffix(".json"), {
        "sample_rate_hz": 50, "window_size": 128, "model_config": config,
        "class_names": train.class_names, "params": params, "augmentation": None,
        "metrics": {"seed": 42, "epoch": epochs}, "train_history": history,
        "selection": "fixed epochs from median inner subject-validation best epochs",
        **metadata,
    })


def load_pool(path):
    with np.load(path) as data:
        return {key: data[key].copy() for key in data.files}


def write_test(pool, subject, folder):
    fields = {"X", "y", "subjects", "sessions", "trials", "filenames", "centre_offsets", "window_centres"}
    mask = pool["subjects"] == subject
    folder.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(folder / "real_gestures_test.npz",
                        **{key: value[mask] if key in fields else value for key, value in pool.items()})


def run(args):
    torch.set_num_threads(args.threads)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    root = args.input.resolve()
    subjects = discover_subjects(root)
    if len(subjects) < 3:
        raise ValueError("Nested LOSO requires at least three subjects")
    settings = candidates()
    started = datetime.now(timezone(timedelta(hours=8)))
    output = args.output.resolve() / started.strftime("%Y-%m-%d_%H-%M-%S_%f")
    output.mkdir(parents=True, exist_ok=False)
    protocol = {
        "protocol": "nested leave-one-subject-out regularization comparison",
        "started_at": started.isoformat(), "subjects": subjects, "input": str(root),
        "inner_max_epochs": args.epochs, "seed": 42, "settings": settings,
        "sample_rate_hz": 50, "window_size": 128, "augmentation": None,
        "offline_window_offsets": "training recordings only, same offsets as existing preprocessing",
        "selection_min_gain_pp": 1.0,
        "selection": "equal-subject mean inner balanced accuracy; >=1pp over current required",
        "epochs": "round-half-up median of winning candidate's inner best epochs",
        "outer_refit": "all recordings from non-test subjects; epochs fixed from inner validation",
        "final_model": "global pooled-inner winner; retain current if outer selected mean gain <1pp",
        "limitations": "development data already used for architecture and prior tuning; one seed",
        "status": "running",
    }
    save_json(output / "protocol.json", protocol)
    print(f"Nested LOSO output: {output}\nDevice: {device}", flush=True)
    pool_dir = output / "pool"
    for name, split in (("centered", "test"), ("augmented", "train")):
        convert(root, pool_dir / name, args.centre_overrides, 50, 128,
                subject_splits={subject: split for subject in subjects})
    centered = load_pool(pool_dir / "centered" / "real_gestures_test.npz")
    augmented = load_pool(pool_dir / "augmented" / "real_gestures_train.npz")
    assert np.all(centered["centre_offsets"] == 0)
    assert len(set(centered["filenames"])) == len(centered["filenames"])
    assert set(centered["filenames"]) == set(augmented["filenames"])
    protocol["pool_sha256"] = {
        str(path.relative_to(output)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in pool_dir.glob("*/*.npz")
    }
    save_json(output / "protocol.json", protocol)
    folds, references = [], []
    all_inner = {name: [] for name in settings}
    reference_dir = output / "current_reference"
    reference_dir.mkdir()
    for outer in subjects:
        print(f"\n=== Outer test subject: {outer} ===", flush=True)
        fold = output / outer
        fold.mkdir()
        development = [s for s in subjects if s != outer]
        inner_results = {name: [] for name in settings}
        manifest = {"test": SubjectWindows(centered, [outer]).manifest(), "inner": []}
        for val_subject in development:
            train_subjects = [s for s in development if s != val_subject]
            train = SubjectWindows(augmented, train_subjects)
            val = SubjectWindows(centered, [val_subject])
            audit_subject_split(train, val, outer)
            manifest["inner"].append({"train": train.manifest(), "val": val.manifest()})
            save_json(fold / "split_manifest.json", manifest)
            for name, params in settings.items():
                result = fit(params, 42, train, val, args.epochs, device)
                result.update(validation_subject=val_subject, training_subjects=train_subjects,
                              outer_test_subject=outer)
                inner_results[name].append(result)
                all_inner[name].append(result)
                save_json(fold / "inner_results.json", inner_results)
                print(f"  validate={val_subject}, setting={name}: "
                      f"{result['balanced_accuracy']:.2f}% at epoch {result['epoch']}", flush=True)
        summary = summarize_inner(inner_results)
        chosen = select_setting(summary)
        save_json(fold / "selection.json", {"chosen": chosen, "candidates": summary,
                                           "outer_test_subject": outer})
        print(f"  Selected {chosen}, refit for {summary[chosen]['refit_epochs']} epochs", flush=True)
        outer_train = SubjectWindows(augmented, development)
        write_test(centered, outer, fold / "data")
        manifest["outer_train"] = outer_train.manifest()
        save_json(fold / "split_manifest.json", manifest)
        # Both selections are fixed above, before either outer model is tested.
        evaluations = {}
        for name in dict.fromkeys((chosen, "current")):
            dest = fold / "models" / f"{name}.pth"
            train_fixed(outer_train, settings[name], summary[name]["refit_epochs"], dest, device,
                        {"outer_test_subject": outer, "training_subjects": development})
            artifacts = fold if name == chosen else fold / "current"
            artifacts.mkdir(exist_ok=True)
            metrics = evaluate_fold(dest, fold / "data", artifacts, 50, 128,
                                    subject_label=f"{outer} ({name})")
            metrics.update(held_out_subject=outer, setting=name,
                           checkpoint=str(dest.relative_to(output)),
                           best_epoch=summary[name]["refit_epochs"])
            save_json(artifacts / "metrics.json", metrics)
            evaluations[name] = metrics
        folds.append(evaluations[chosen])
        references.append(evaluations["current"])
        selected_summary = write_summary(output, folds)
        current_summary = write_summary(reference_dir, references)
        print(f"  OUTER {outer}: selected={evaluations[chosen]['balanced_accuracy']:.2f}%, "
              f"current={evaluations['current']['balanced_accuracy']:.2f}%", flush=True)
    global_summary = summarize_inner(all_inner)
    final_setting = select_setting(global_summary)
    gain = (selected_summary["aggregate"]["balanced_accuracy"]["mean"]
            - current_summary["aggregate"]["balanced_accuracy"]["mean"])
    if gain < 1.0:
        final_setting = "current"
    recommendation = {
        "setting": final_setting, "params": settings[final_setting],
        "epochs": global_summary[final_setting]["refit_epochs"],
        "pooled_inner": global_summary, "outer_selected_gain_pp": gain,
        "reason": "retain current unless both inner selection and outer development comparison support >=1pp gain",
        "deployment_model_evaluation": "none: final model uses all development subjects",
    }
    save_json(output / "recommendation.json", recommendation)
    with (output / "comparison.csv").open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["held_out_subject", "selected_setting", "selected_balanced_accuracy",
                         "current_balanced_accuracy", "change_pp"])
        for selected, current in zip(folds, references):
            writer.writerow([selected["held_out_subject"], selected["setting"], selected["balanced_accuracy"],
                             current["balanced_accuracy"], selected["balanced_accuracy"] - current["balanced_accuracy"]])
        writer.writerow(["mean", "", selected_summary["aggregate"]["balanced_accuracy"]["mean"],
                         current_summary["aggregate"]["balanced_accuracy"]["mean"], gain])
    final_path = output / "deployment_candidate" / "gesture_1dcnn_real_50hz_128.pth"
    print(f"\nFinal candidate: {final_setting}, {recommendation['epochs']} epochs, all subjects", flush=True)
    train_fixed(SubjectWindows(augmented, subjects), settings[final_setting], recommendation["epochs"],
                final_path, device, {"training_subjects": subjects, "independent_test_accuracy": None})
    protocol.update(status="complete", deployment_candidate=str(final_path.relative_to(output)))
    save_json(output / "protocol.json", protocol)
    print(f"Selected procedure: {selected_summary['aggregate']['balanced_accuracy']}", flush=True)
    print(f"Matched current: {current_summary['aggregate']['balanced_accuracy']}", flush=True)
    print(f"Deployment candidate: {final_path}", flush=True)
    return output


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=ULTRA96_DIR / "real_data")
    parser.add_argument("--output", type=Path, default=ULTRA96_DIR / "pytorch" / "loso_runs" / "regularization")
    parser.add_argument("--centre-overrides", type=Path)
    parser.add_argument("--epochs", type=int, default=30)
    parser.add_argument("--threads", type=int, default=4)
    args = parser.parse_args()
    if args.epochs < 1 or args.threads < 1:
        parser.error("epochs and threads must be positive")
    return args


if __name__ == "__main__":
    run(parse_args())
