"""Modest real-data search; never loads the test split or replaces baseline weights."""
import argparse
import json
from pathlib import Path
import sys

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import optuna
import torch
from torch import nn
from torch.utils.data import DataLoader

from ultra96.pytorch.training.model import Gesture1DCNN
from ultra96.pytorch.training.train_baseline import (
    NPZIMUDataset, REAL_DATA_DIR, PYTORCH_DIR, set_seed,
)

BASELINE = {"lr": 1e-3, "weight_decay": 1e-4, "dropout": 0.3}


def fit(params, seed, train, val, epochs, device, trial=None, checkpoint=None):
    set_seed(seed)
    classes = len(train.class_names)
    model = Gesture1DCNN(in_channels=6, num_classes=classes).to(device)
    model.classifier[0].p = params["dropout"]
    counts = torch.bincount(train.labels, minlength=classes).float()
    weights = len(train) / (classes * counts)
    criterion = nn.CrossEntropyLoss(weight=weights.to(device))
    optimizer = torch.optim.Adam(model.parameters(), lr=params["lr"],
                                 weight_decay=params["weight_decay"])
    train_loader = DataLoader(train, batch_size=32, shuffle=True)
    val_loader = DataLoader(val, batch_size=32, shuffle=False)
    best, best_loss, best_epoch = -1.0, float("inf"), 0
    for epoch in range(1, epochs + 1):
        model.train()
        for x, y in train_loader:
            x, y = x.to(device), y.to(device)
            optimizer.zero_grad()
            loss = criterion(model(x), y)
            loss.backward()
            optimizer.step()
        model.eval()
        cm = torch.zeros(classes * classes, dtype=torch.int64, device=device)
        loss_sum, weight_sum = 0.0, 0.0
        with torch.no_grad():
            for x, y in val_loader:
                x, y = x.to(device), y.to(device)
                logits = model(x)
                cm += torch.bincount(y * classes + logits.argmax(1),
                                     minlength=classes * classes)
                loss_sum += nn.functional.cross_entropy(
                    logits, y, weight=weights.to(device), reduction="sum").item()
                weight_sum += weights.to(device)[y].sum().item()
        cm = cm.reshape(classes, classes)
        score = (cm.diag() / cm.sum(1)).mean().item() * 100
        val_loss = loss_sum / weight_sum
        if score > best or (score == best and val_loss < best_loss):
            best, best_loss, best_epoch = score, val_loss, epoch
            if checkpoint:
                torch.save(model.state_dict(), checkpoint)
        if trial is not None:
            trial.report(best, epoch)
            if trial.should_prune():
                raise optuna.TrialPruned()
    return {"seed": seed, "balanced_accuracy": best,
            "val_loss": best_loss, "epoch": best_epoch}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trials", type=int, default=20)
    parser.add_argument("--epochs", type=int, default=30)
    parser.add_argument("--data-dir", type=Path, default=Path(REAL_DATA_DIR))
    parser.add_argument("--output-dir", type=Path,
                        default=Path(PYTORCH_DIR) / "saved_checkpoints" / "optuna_real")
    args = parser.parse_args()
    torch.set_num_threads(4)
    if args.trials < 1 or args.epochs < 1:
        parser.error("trials and epochs must be positive")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    # A fresh directory prevents accidental overwrites or mixing different datasets.
    report_path = args.output_dir / "results.json"
    db_path = args.output_dir / "study.db"
    if db_path.exists() or report_path.exists():
        parser.error("output directory already contains a study; choose a new --output-dir")
    train = NPZIMUDataset(args.data_dir / "real_gestures_train.npz")
    val = NPZIMUDataset(args.data_dir / "real_gestures_val.npz")
    classes = len(train.class_names)
    if train.class_names != val.class_names:
        raise ValueError("Class names differ between splits")
    for name, data in (("train", train), ("val", val)):
        if not len(data) or torch.any(torch.bincount(data.labels, minlength=classes) == 0):
            raise ValueError(f"{name} must contain every class")
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Device: {device}; train={len(train)}, val={len(val)}", flush=True)
    study = optuna.create_study(
        direction="maximize", storage=f"sqlite:///{db_path.resolve().as_posix()}",
        sampler=optuna.samplers.TPESampler(seed=42, n_startup_trials=8),
        pruner=optuna.pruners.MedianPruner(n_startup_trials=5, n_warmup_steps=10),
    )
    study.enqueue_trial(BASELINE)

    def objective(trial):
        params = {"lr": trial.suggest_float("lr", 1e-4, 3e-3, log=True),
                  "weight_decay": trial.suggest_float("weight_decay", 1e-6, 1e-2, log=True),
                  "dropout": trial.suggest_float("dropout", 0.1, 0.5)}
        result = fit(params, 42, train, val, args.epochs, device, trial)
        trial.set_user_attr("best_epoch", result["epoch"])
        return result["balanced_accuracy"]

    study.optimize(objective, n_trials=args.trials, n_jobs=1)
    completed = sorted((t for t in study.trials
                        if t.state == optuna.trial.TrialState.COMPLETE),
                       key=lambda t: t.value, reverse=True)
    # Include the baseline explicitly even when it is outside the top two.
    candidates = [("baseline", BASELINE)]
    for trial in completed:
        if trial.params not in [p for _, p in candidates]:
            candidates.append((f"trial_{trial.number}", trial.params))
        if len(candidates) == 3:
            break
    results = []
    for name, params in candidates:
        runs = []
        for seed in (42, 43, 44):
            checkpoint = args.output_dir / f"{name}_seed_{seed}.pth"
            run = fit(params, seed, train, val, args.epochs, device, checkpoint=checkpoint)
            run["checkpoint"] = checkpoint.name
            runs.append(run)
            print(f"{name}: {run}", flush=True)
        scores = [r["balanced_accuracy"] for r in runs]
        mean = sum(scores) / len(scores)
        results.append({"name": name, "params": params, "runs": runs,
                        "mean_balanced_accuracy": mean,
                        "std_balanced_accuracy": (sum((s-mean)**2 for s in scores)/len(scores))**0.5})
        report_path.write_text(json.dumps({"epochs": args.epochs,
            "class_names": train.class_names, "candidates": results,
            "test_evaluated": False}, indent=2) + "\n")
    winner = max(results, key=lambda r: r["mean_balanced_accuracy"])
    print(f"Best mean validation score: {winner['name']} {winner['mean_balanced_accuracy']:.2f}%")
    print(f"Results: {report_path}")


if __name__ == "__main__":
    main()
