"""Search real-data CNN architectures/training settings using train and validation only.

Each finalist gets three seeds, raw state-dict checkpoints, and matching JSON
model configurations. Architecture changes require matching HLS/export changes.
"""
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
    NPZIMUDataset, REAL_DATA_DIR, PYTORCH_DIR, REAL_TRAINING_PARAMS, set_seed,
)

BASE_ARCHITECTURE = {"base_channels": 32, "kernel1": 7, "kernel2": 5,
                     "kernel3": 3, "hidden_features": 64}
SEARCH_SPACE = {"base_channels": [16, 24, 32], "kernel1": [3, 5, 7],
                "kernel2": [3, 5], "kernel3": [3, 5],
                "hidden_features": [32, 64, 128]}


def model_config(params, classes):
    architecture = {**BASE_ARCHITECTURE, **params}
    width = architecture["base_channels"]
    return {"in_channels": 6, "num_classes": classes,
            "channels": [width, width * 2, width * 4],
            "kernel_sizes": [architecture[f"kernel{i}"] for i in (1, 2, 3)],
            "hidden_features": architecture["hidden_features"],
            "dropout": params["dropout"]}


def model_cost(config):
    """Exact trainable parameter count and Conv/Linear MAC estimate per window.

    MACs exclude BN, activations and pooling; neither number predicts FPGA fit.
    """
    channels = [config["in_channels"], *config["channels"]]
    parameters, macs = 0, 0
    for i, (kernel, length) in enumerate(zip(config["kernel_sizes"], (256, 128, 64))):
        inputs, outputs = channels[i:i + 2]
        parameters += outputs * (inputs * kernel + 3)  # Conv bias + BN gamma/beta
        macs += length * outputs * inputs * kernel
    features, hidden, classes = channels[-1], config["hidden_features"], config["num_classes"]
    parameters += (features + 1) * hidden + (hidden + 1) * classes
    macs += features * hidden + hidden * classes
    return {"parameters": parameters, "estimated_macs": macs,
            "requires_hls_changes": (config["channels"] != [32, 64, 128] or
                                     config["kernel_sizes"] != [7, 5, 3] or hidden != 64)}


def fit(params, seed, train, val, epochs, device, trial=None, checkpoint=None):
    set_seed(seed)
    classes = len(train.class_names)
    config = model_config(params, classes)
    model = Gesture1DCNN(**config).to(device)
    counts = torch.bincount(train.labels, minlength=classes).float()
    weights = len(train) / (classes * counts)
    criterion = nn.CrossEntropyLoss(weight=weights.to(device))
    optimizer = torch.optim.Adam(model.parameters(), lr=params["lr"],
                                 weight_decay=params["weight_decay"])
    train_loader = DataLoader(train, batch_size=32, shuffle=True)
    val_loader = DataLoader(val, batch_size=32, shuffle=False)
    best, best_loss, best_epoch = -1.0, float("inf"), 0
    best_recalls = None
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
            best_recalls = (cm.diag() / cm.sum(1)).cpu().tolist()
            if checkpoint:
                torch.save(model.state_dict(), checkpoint)
        if trial is not None:
            trial.report(best, epoch)
            if trial.should_prune():
                raise optuna.TrialPruned()
    result = {"seed": seed, "balanced_accuracy": best,
              "val_loss": best_loss, "epoch": best_epoch,
              "per_class_recall": dict(zip(train.class_names, best_recalls))}
    if checkpoint:
        Path(checkpoint).with_suffix(".json").write_text(json.dumps({
            "model_config": config, "class_names": train.class_names,
            "params": params, "metrics": result}, indent=2) + "\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trials", type=int, default=40)
    parser.add_argument("--epochs", type=int, default=30)
    parser.add_argument("--data-dir", type=Path, default=Path(REAL_DATA_DIR))
    parser.add_argument("--output-dir", type=Path,
                        default=Path(PYTORCH_DIR) / "saved_checkpoints" / "optuna_architecture")
    parser.add_argument("--search", choices=("architecture", "hyperparameters", "joint"),
                        default="joint", help="architecture fixes training settings to the current tuned model")
    parser.add_argument("--max-params", type=int, default=None,
                        help="prune models above this trainable parameter budget")
    parser.add_argument("--max-macs", type=int, default=None,
                        help="prune models above this estimated Conv/Linear MAC budget per window")
    args = parser.parse_args()
    torch.set_num_threads(4)
    if args.trials < 1 or args.epochs < 1:
        parser.error("trials and epochs must be positive")
    if any(value is not None and value < 1 for value in (args.max_params, args.max_macs)):
        parser.error("resource budgets must be positive")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    # A fresh directory prevents accidental overwrites or mixing different datasets.
    report_path = args.output_dir / "results.json"
    db_path = args.output_dir / "study.db"
    if any(args.output_dir.iterdir()):
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
    baseline = {**BASE_ARCHITECTURE, **REAL_TRAINING_PARAMS}
    baseline_cost = model_cost(model_config(baseline, classes))
    if ((args.max_params and baseline_cost["parameters"] > args.max_params) or
            (args.max_macs and baseline_cost["estimated_macs"] > args.max_macs)):
        parser.error(f"budget excludes the baseline: {baseline_cost}")
    storage = optuna.storages.RDBStorage(f"sqlite:///{db_path.resolve().as_posix()}")
    study = optuna.create_study(
        direction="maximize", storage=storage,
        sampler=optuna.samplers.TPESampler(seed=42, n_startup_trials=8),
        pruner=optuna.pruners.MedianPruner(n_startup_trials=5, n_warmup_steps=10),
    )
    queued = dict(baseline)
    if args.search == "architecture":
        queued = {key: baseline[key] for key in SEARCH_SPACE}
    elif args.search == "hyperparameters":
        queued = dict(REAL_TRAINING_PARAMS)
    study.enqueue_trial(queued)

    def objective(trial):
        params = dict(baseline)
        if args.search != "hyperparameters":
            params.update({name: trial.suggest_categorical(name, choices)
                           for name, choices in SEARCH_SPACE.items()})
        if args.search != "architecture":
            params.update({"lr": trial.suggest_float("lr", 1e-4, 3e-3, log=True),
                           "weight_decay": trial.suggest_float("weight_decay", 1e-6, 1e-2, log=True),
                           "dropout": trial.suggest_float("dropout", 0.1, 0.5)})
        config = model_config(params, classes)
        cost = model_cost(config)
        trial.set_user_attr("resolved_params", params)
        trial.set_user_attr("model_config", config)
        for key, value in cost.items():
            trial.set_user_attr(key, value)
        if ((args.max_params and cost["parameters"] > args.max_params) or
                (args.max_macs and cost["estimated_macs"] > args.max_macs)):
            raise optuna.TrialPruned("Model exceeds resource budget")
        print(f"Trial {trial.number}: {params}; {cost}", flush=True)
        result = fit(params, 42, train, val, args.epochs, device, trial)
        trial.set_user_attr("best_epoch", result["epoch"])
        return result["balanced_accuracy"]

    try:
        study.optimize(objective, n_trials=args.trials, n_jobs=1)
        completed = sorted((t for t in study.trials
                            if t.state == optuna.trial.TrialState.COMPLETE),
                           key=lambda t: t.value, reverse=True)
    finally:
        # Release SQLite handles, including on Windows and interrupted searches.
        storage.remove_session()
        storage.engine.dispose()
    # Include the baseline explicitly even when it is outside the top two.
    candidates = [("baseline", baseline)]
    for trial in completed:
        params = trial.user_attrs["resolved_params"]
        if params not in [p for _, p in candidates]:
            candidates.append((f"trial_{trial.number}", params))
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
        config = model_config(params, classes)
        results.append({"name": name, "params": params, "model_config": config,
                        **model_cost(config), "runs": runs,
                        "mean_balanced_accuracy": mean,
                        "std_balanced_accuracy": (sum((s-mean)**2 for s in scores)/len(scores))**0.5})
        report_path.write_text(json.dumps({"epochs": args.epochs, "search": args.search,
            "data_dir": str(args.data_dir.resolve()),
            "search_space": SEARCH_SPACE if args.search != "hyperparameters" else {},
            "max_params": args.max_params, "max_macs": args.max_macs,
            "baseline_training_params": REAL_TRAINING_PARAMS,
            "class_names": train.class_names, "candidates": results,
            "test_evaluated": False}, indent=2) + "\n")
    winner = max(results, key=lambda r: r["mean_balanced_accuracy"])
    winner_run = max(winner["runs"], key=lambda r: (r["balanced_accuracy"], -r["val_loss"]))
    winner_path = args.output_dir / "winner.json"
    winner_path.write_text(json.dumps({**winner, "selected_checkpoint": winner_run["checkpoint"],
        "selection": "Best three-seed mean validation balanced accuracy; checkpoint selected by validation score",
        "test_evaluated": False}, indent=2) + "\n")
    print(f"Best mean validation score: {winner['name']} {winner['mean_balanced_accuracy']:.2f}%")
    print(f"Selected checkpoint: {args.output_dir / winner_run['checkpoint']}")
    print(f"Architecture: {winner['model_config']}; requires HLS changes: {winner['requires_hls_changes']}")
    print(f"Results: {report_path}")


if __name__ == "__main__":
    main()
