import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import Dataset, DataLoader
import matplotlib.pyplot as plt
import argparse
from datetime import datetime, timedelta, timezone
import json
import os, numpy as np
import sys
from pathlib import Path

# Support both direct script execution and python -m from the repository root.
if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from ultra96.pytorch.training.model import Gesture1DCNN, MODEL_PRESETS
from ultra96.pytorch.training.augmentation import make_training_augmentation

SAMPLE_RATE_HZ = 50
WINDOW_SIZE = 128
def run_label(sample_rate, window_size):
    return f"{sample_rate} Hz | {window_size}-sample window ({window_size / sample_rate:.2f} s)"


def validate_input_settings(sample_rate, window_size):
    if sample_rate <= 0 or window_size < 4:
        raise ValueError("sample_rate must be positive and window_size must be at least 4")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PYTORCH_DIR = os.path.dirname(SCRIPT_DIR)
ULTRA96_DIR = os.path.dirname(PYTORCH_DIR)
REAL_DATA_DIR = os.path.normpath(os.path.join(
    ULTRA96_DIR, "real_data", "processed_50hz_128"
))
UTD_DATA_DIR = os.path.normpath(os.path.join(
    ULTRA96_DIR, "online_data", "UTD-MHAD_HumanActionRecognitionDataset",
    "utd_mhad_processed_50hz_128"
))
DATASET_CONFIGS = {
    "real": (REAL_DATA_DIR, "real_gestures"),
    "utd": (UTD_DATA_DIR, "utd_mhad"),
}

# Hyperparameters from trial 42 of optuna_architecture_wide (legacy CNN).
# The temporal preset has not been retuned. UTD keeps its original defaults.
REAL_TRAINING_PARAMS = {
    "lr": 0.0011709413361488715,
    "weight_decay": 0.00016330261109656093,
    "dropout": 0.22214197961920232,
}

def resolve_software_checkpoint(dataset="real", sample_rate=SAMPLE_RATE_HZ, window_size=WINDOW_SIZE):
    """Find the latest completed matching software run, including configuration folders."""
    root = Path(PYTORCH_DIR) / "saved_checkpoints"
    candidates = []
    for metadata_path in root.rglob("run.json"):
        metadata = json.loads(metadata_path.read_text())
        if (metadata.get("dataset") == dataset and metadata.get("sample_rate_hz") == sample_rate
                and metadata.get("window_size") == window_size and metadata.get("checkpoint")):
            path = metadata_path.parent / Path(metadata["checkpoint"]).name
            if path.is_file():
                candidates.append(path)
    if candidates:
        return max(candidates, key=lambda path: (path.parent.name, str(path)))
    return root / f"{sample_rate}hz_{window_size}" / f"gesture_1dcnn_{dataset}_{sample_rate}hz_{window_size}_best.pth"


def set_seed(seed=42):
    """Sets the seed for reproducibility."""
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed(seed)
        torch.cuda.manual_seed_all(seed)  # if you are using multi-GPU.
        # The two lines below are known to slow down training, but ensure reproducibility
        torch.backends.cudnn.deterministic = True
        torch.backends.cudnn.benchmark = False

class NPZIMUDataset(Dataset):
    """CNN-ready IMU windows loaded from an NPZ containing X and y."""

    def __init__(self, path, sample_rate=SAMPLE_RATE_HZ, window_size=WINDOW_SIZE):
        validate_input_settings(sample_rate, window_size)
        self.sample_rate = sample_rate
        self.window_size = window_size
        with np.load(path) as dataset:
            self.data = torch.from_numpy(
                np.asarray(dataset["X"], dtype=np.float32).copy()
            )
            self.labels = torch.from_numpy(
                np.asarray(dataset["y"], dtype=np.int64).copy()
            )
            self.class_names = dataset["class_names"].tolist()
            if "sample_rate_hz" in dataset and float(dataset["sample_rate_hz"].item()) != sample_rate:
                raise ValueError(f"{path}: expected {sample_rate} Hz data")
            if "window_size" in dataset and int(dataset["window_size"].item()) != window_size:
                raise ValueError(f"{path}: expected {window_size}-sample windows")
        if self.data.ndim != 3 or tuple(self.data.shape[1:]) != (6, window_size):
            raise ValueError(f"{path}: X must have shape [N, 6, {window_size}]")
        if self.labels.shape != (len(self.data),):
            raise ValueError(f"{path}: y must have one label per window")

    def __len__(self):
        return len(self.data)

    def __getitem__(self, idx):
        return self.data[idx], self.labels[idx]


# =====================================================================
# 2. REAL-TIME POST-PROCESSING (CONFIDENCE & DEBOUNCE FILTER)
# =====================================================================
class RealTimeGesturePredictor:
    """
    Handles streaming inference with confidence thresholding and cooldown.
    """
    def __init__(self, model, confidence_threshold=0.75, debounce_cooldown_steps=10, idle_class_idx=0, class_map=None):
        self.model = model
        self.model.eval()
        self.confidence_threshold = confidence_threshold
        self.cooldown_steps = debounce_cooldown_steps
        self.idle_class_idx = idle_class_idx
        self.cooldown_counter = 0
        self.class_map = class_map if class_map is not None else {}

    def _get_class_name(self, class_idx):
        """Returns the gesture name from the class index."""
        if class_idx is None:
            return "None"
        return self.class_map.get(class_idx, str(class_idx))

    @torch.no_grad()
    def predict_window(self, window_tensor):
        """
        window_tensor shape: (1, 6, window_size)
        """
        if self.cooldown_counter > 0:
            self.cooldown_counter -= 1
            return self._get_class_name(None), 0.0, "COOLDOWN_ACTIVE"

        logits = self.model(window_tensor)
        probs = torch.softmax(logits, dim=1)
        top_prob, top_idx = torch.max(probs, dim=1)

        pred_class = top_idx.item()
        confidence = top_prob.item()

        # Reject low confidence or Idle class
        if confidence < self.confidence_threshold:
            return self._get_class_name(None), confidence, "LOW_CONFIDENCE"
        if pred_class == self.idle_class_idx:
            return self._get_class_name(None), confidence, "IDLE_IGNORED"

        # Valid trigger -> Activate cooldown debounce
        self.cooldown_counter = self.cooldown_steps
        return self._get_class_name(pred_class), confidence, "TRIGGERED"

# =====================================================================
# 3. TRAINING & VALIDATION PIPELINE
# =====================================================================
def run_pipeline(num_epochs=30, dataset="real", data_dir=None, checkpoint=None,
                 output_dir=None, evaluate=False, eval_data=None,
                 sample_rate=SAMPLE_RATE_HZ, window_size=WINDOW_SIZE,
                 training_params=None, augmentation=None, architecture=None):
    validate_input_settings(sample_rate, window_size)
    architecture = "temporal" if architecture is None else architecture
    if architecture not in MODEL_PRESETS:
        raise ValueError(f"Unknown architecture: {architecture}")
    if window_size // 4 < MODEL_PRESETS[architecture].get("temporal_bins", 1):
        raise ValueError("Window must have at least 4 * temporal_bins samples")
    label = run_label(sample_rate, window_size)
    if num_epochs < 1:
        raise ValueError("epochs must be positive")
    if eval_data is not None and not evaluate:
        raise ValueError("eval_data requires evaluate=True")
    # Set seed for deterministic results
    set_seed(42)
    augmenter = make_training_augmentation(augmentation) if augmentation is not None else None
    augmentation_config = augmenter.config if augmenter else None

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Run configuration: {label}")
    print(f"Using device: {device}")

    # Load fixed [6, window_size] windows; shuffle training only.
    default_data_dir, file_prefix = DATASET_CONFIGS[dataset]
    data_dir = data_dir or default_data_dir
    train_dataset = NPZIMUDataset(os.path.join(data_dir, f"{file_prefix}_train.npz"), sample_rate, window_size)
    val_dataset = NPZIMUDataset(os.path.join(data_dir, f"{file_prefix}_val.npz"), sample_rate, window_size)
    gesture_map = dict(enumerate(train_dataset.class_names))
    checkpoint_name = f"gesture_1dcnn_{dataset}_{sample_rate}hz_{window_size}_best.pth"

    num_classes = len(gesture_map)
    if val_dataset.class_names != train_dataset.class_names:
        raise ValueError("Training and validation datasets have different classes")
    if not len(train_dataset) or not len(val_dataset):
        raise ValueError("Training and validation datasets must not be empty")
    evaluation_path = Path(eval_data or os.path.join(data_dir, f"{file_prefix}_test.npz"))
    if evaluate:
        evaluation_dataset = NPZIMUDataset(evaluation_path, sample_rate, window_size)
        if (not len(evaluation_dataset) or
                evaluation_dataset.class_names != train_dataset.class_names):
            raise ValueError("Evaluation dataset must be nonempty and have the training class order")

    # Every run owns its artifacts. Microseconds avoid collisions between fast runs.
    requested_checkpoint = Path(checkpoint) if checkpoint else Path(checkpoint_name)
    default_root = (requested_checkpoint.parent if requested_checkpoint.parent != Path(".")
                    else Path(PYTORCH_DIR) / "saved_checkpoints" / "50hz_128")
    output_root = Path(output_dir) if output_dir is not None else default_root
    started_at = datetime.now(timezone(timedelta(hours=8), "Asia/Singapore"))
    run_dir = output_root / started_at.strftime("%Y-%m-%d_%H-%M-%S_%f")
    run_dir.mkdir(parents=True, exist_ok=False)
    best_model_path = run_dir / requested_checkpoint.name
    plot_path = run_dir / f"gesture_1dcnn_{dataset}_{sample_rate}hz_{window_size}_loss.png"
    matrix_path = run_dir / f"{file_prefix}_{sample_rate}hz_{window_size}_confusion_matrix.png"
    print(f"Run folder (Singapore time): {run_dir.resolve()}")

    train_loader = DataLoader(train_dataset, batch_size=32, shuffle=True)
    val_loader = DataLoader(val_dataset, batch_size=32, shuffle=False)

    print("Classes:", gesture_map)

    params = REAL_TRAINING_PARAMS if dataset == "real" else {
        "lr": 1e-3, "weight_decay": 1e-4, "dropout": 0.3,
    }
    if training_params is not None:
        params = {**params, **training_params}
    model = Gesture1DCNN(in_channels=6, num_classes=num_classes,
                         dropout=params["dropout"], **MODEL_PRESETS[architecture]).to(device)
    print("Model settings:", model.config)
    print("Convolutional context:", model.receptive_field_samples, "samples")
    print("Training settings:", params)
    # Inverse-frequency weights give each gesture equal importance in the loss.
    counts = torch.bincount(train_dataset.labels, minlength=num_classes).float()
    if torch.any(counts == 0):
        raise ValueError(f"Training data is missing a class: {counts.tolist()}")
    class_weights = len(train_dataset) / (num_classes * counts)
    criterion = nn.CrossEntropyLoss(weight=class_weights.to(device))
    print("Class counts:", counts.to(torch.int64).tolist())
    print("Loss weights:", [round(value, 4) for value in class_weights.tolist()])
    optimizer = optim.Adam(model.parameters(), lr=params["lr"],
                           weight_decay=params["weight_decay"])

    best_val_balanced_acc = -1.0
    best_val_loss = float('inf')
    best_epoch = 0
    train_losses = []
    val_losses = []

    print("\n--- Starting Model Training ---")
    for epoch in range(1, num_epochs + 1):
        # Training Phase
        model.train()
        total_loss, correct, total = 0.0, 0, 0
        for inputs, targets in train_loader:
            if augmenter is not None:
                inputs = augmenter(inputs)
            inputs, targets = inputs.to(device), targets.to(device)

            # Forward -> measure error -> backpropagate -> update model weights.
            optimizer.zero_grad()
            outputs = model(inputs)
            loss = criterion(outputs, targets)
            loss.backward()
            optimizer.step()

            total_loss += loss.item() * inputs.size(0)
            _, predicted = outputs.max(1)
            total += targets.size(0)
            correct += predicted.eq(targets).sum().item()

        train_acc = 100.0 * correct / total
        train_loss = total_loss / total

        # Validation measures generalization without changing any weights.
        model.eval()
        val_loss, val_correct, val_total = 0.0, 0, 0
        val_cm = torch.zeros((num_classes, num_classes), dtype=torch.int64)
        with torch.no_grad():
            for inputs, targets in val_loader:
                inputs, targets = inputs.to(device), targets.to(device)
                outputs = model(inputs)
                loss = criterion(outputs, targets)
                val_loss += loss.item() * inputs.size(0)
                _, predicted = outputs.max(1)
                val_total += targets.size(0)
                val_correct += predicted.eq(targets).sum().item()
                for target, prediction in zip(targets.cpu(), predicted.cpu()):
                    val_cm[target, prediction] += 1

        val_acc = 100.0 * val_correct / val_total
        val_recall = val_cm.diag().float() / val_cm.sum(dim=1).clamp_min(1)
        val_balanced_acc = 100.0 * val_recall.mean().item()
        avg_val_loss = val_loss / val_total
        train_losses.append(train_loss)
        val_losses.append(avg_val_loss)
        print(f"Epoch [{epoch:02d}/{num_epochs:02d}] | Train Loss: {train_loss:.4f} | Train Acc: {train_acc:.2f}% | Val Loss: {avg_val_loss:.4f} | Val Acc: {val_acc:.2f}% | Val Balanced Acc: {val_balanced_acc:.2f}%", end="")

        # Save the epoch with the best mean recall across all gesture classes.
        if (val_balanced_acc > best_val_balanced_acc or
                (val_balanced_acc == best_val_balanced_acc and
                 avg_val_loss < best_val_loss)):
            best_val_balanced_acc = val_balanced_acc
            best_val_loss = avg_val_loss
            best_epoch = epoch
            torch.save(model.state_dict(), best_model_path)
            print(f"  -> New best model saved to {best_model_path} (Val Balanced Acc: {best_val_balanced_acc:.2f}%, Val Loss: {best_val_loss:.4f})")
        else:
            print() # Newline if no model was saved

    if train_losses:
        epochs = range(1, len(train_losses) + 1)
        fig, ax = plt.subplots()
        ax.plot(epochs, train_losses, label="Training loss")
        ax.plot(epochs, val_losses, label="Validation loss")
        ax.set_xlabel("Epoch")
        ax.set_ylabel("Cross-entropy loss")
        ax.set_title(f"{dataset.upper()} training and validation loss\n{label}")
        ax.legend()
        ax.grid(True, alpha=0.3)
        fig.tight_layout()
        fig.savefig(plot_path)
        plt.close(fig)
        print(f"Loss plot saved to '{plot_path}'")

    print("\n--- Training Complete ---")
    print(f"Best model saved to '{best_model_path}' with Validation Balanced Accuracy: {best_val_balanced_acc:.2f}%")
    # The evaluator reads this sidecar to recover architecture and class order.
    best_model_path.with_suffix(".json").write_text(json.dumps({
        "sample_rate_hz": sample_rate, "window_size": window_size,
        "model_config": {**model.config, "dropout": params["dropout"]},
        "class_names": train_dataset.class_names, "params": params,
        "augmentation": augmentation_config,
        "metrics": {"seed": 42, "epoch": best_epoch,
                    "balanced_accuracy": best_val_balanced_acc, "val_loss": best_val_loss},
    }, indent=2) + "\n")
    metadata = {"started_at": started_at.isoformat(), "dataset": dataset,
                "architecture": architecture, "model_config": model.config,
                "sample_rate_hz": sample_rate, "window_size": window_size,
                "data_dir": str(Path(data_dir).resolve()), "epochs": num_epochs,
                "params": params, "checkpoint": best_model_path.name,
                "augmentation": augmentation_config,
                "loss_plot": plot_path.name, "best_epoch": best_epoch,
                "best_val_balanced_accuracy": best_val_balanced_acc,
                "train_losses": train_losses, "val_losses": val_losses,
                "evaluation_data": str(evaluation_path.resolve()) if evaluate else None,
                "evaluation_completed": False}
    metadata_path = run_dir / "run.json"
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n")
    if evaluate:
        # Reuse the standalone evaluator, explicitly loading the best saved epoch.
        from ultra96.pytorch.training.evaluate_model import main as evaluate_model
        evaluate_model(argparse.Namespace(data=str(evaluation_path), data_dir=None,
                                         checkpoint=str(best_model_path), output=str(matrix_path),
                                         sample_rate=sample_rate, window_size=window_size))
        metadata.update(evaluation_completed=True, confusion_matrix=matrix_path.name)
        metadata_path.write_text(json.dumps(metadata, indent=2) + "\n")
    return run_dir


def parse_args():
    parser = argparse.ArgumentParser(description="Train the gesture 1D CNN")
    parser.add_argument("--epochs", type=int, default=30)
    aug = parser.add_mutually_exclusive_group()
    aug.add_argument("--augment", action="store_true",
                        help="apply small amplitude, noise and speed changes to training batches only")
    aug.add_argument("--augmentation", choices=("basic", "imu"),
                     help="training-only preset: basic or shared 3D rotation, smooth time warp and magnitude")
    parser.add_argument("--dataset", choices=DATASET_CONFIGS, default="real")
    parser.add_argument("--architecture", choices=MODEL_PRESETS, default="temporal",
                        help="model architecture: temporal uses kernel sizes (7, 5, 7) with dilations (1, 2, 4); "
                             "legacy uses kernel sizes (7, 5, 3) with dilation 1 (default: temporal)")
    parser.add_argument("--data-dir", default=None,
                        help="override the selected dataset processed directory (real default: real_data/processed_50hz_128)")
    parser.add_argument("--checkpoint", default=None,
                        help="checkpoint filename; a path uses its parent as the output root unless --output-dir is given")
    parser.add_argument("--output-dir", type=Path, default=None,
                        help="parent for dated run folders (default: pytorch/saved_checkpoints/50hz_128)")
    parser.add_argument("--evaluate", action="store_true",
                        help="evaluate the best checkpoint and save its confusion matrix in the run folder")
    parser.add_argument("--eval-data", type=Path, default=None,
                        help="evaluation NPZ for --evaluate; defaults to the selected dataset test split")
    parser.add_argument("--sample-rate", type=int, default=SAMPLE_RATE_HZ,
                        help="expected dataset sampling rate in Hz (default: 50)")
    parser.add_argument("--window-size", type=int, default=WINDOW_SIZE,
                        help="expected samples per window, at least 4 (default: 128)")
    args = parser.parse_args()
    if args.sample_rate <= 0 or args.window_size < 4:
        parser.error("--sample-rate must be positive and --window-size must be at least 4")
    if args.epochs < 1:
        parser.error("--epochs must be positive")
    if args.eval_data is not None and not args.evaluate:
        parser.error("--eval-data requires --evaluate")
    return args


if __name__ == "__main__":
    args = parse_args()
    run_pipeline(args.epochs, args.dataset, args.data_dir, args.checkpoint,
                 args.output_dir, args.evaluate, args.eval_data,
                 args.sample_rate, args.window_size,
                 architecture=args.architecture,
                 augmentation={"kind": args.augmentation or "basic"}
                 if args.augment or args.augmentation else None)
