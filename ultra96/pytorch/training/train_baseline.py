import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import Dataset, DataLoader
import matplotlib.pyplot as plt
import argparse
import os, numpy as np
import sys
from pathlib import Path

# Support both direct script execution and python -m from the repository root.
if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from ultra96.pytorch.training.model import Gesture1DCNN # Import the model from its dedicated file

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PYTORCH_DIR = os.path.dirname(SCRIPT_DIR)
ULTRA96_DIR = os.path.dirname(PYTORCH_DIR)
REAL_DATA_DIR = os.path.normpath(os.path.join(
    ULTRA96_DIR, "real_data", "processed"
))
UTD_DATA_DIR = os.path.normpath(os.path.join(
    ULTRA96_DIR, "online_data", "UTD-MHAD_HumanActionRecognitionDataset",
    "utd_mhad_processed"
))
DATASET_CONFIGS = {
    "real": (REAL_DATA_DIR, "real_gestures"),
    "utd": (UTD_DATA_DIR, "utd_mhad"),
}

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

    def __init__(self, path):
        with np.load(path) as dataset:
            self.data = torch.from_numpy(
                np.asarray(dataset["X"], dtype=np.float32).copy()
            )
            self.labels = torch.from_numpy(
                np.asarray(dataset["y"], dtype=np.int64).copy()
            )
            self.class_names = dataset["class_names"].tolist()
        if self.data.ndim != 3 or tuple(self.data.shape[1:]) != (6, 256):
            raise ValueError(f"{path}: X must have shape [N, 6, 256]")
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
        window_tensor shape: (1, 6, 256)
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
def run_pipeline(num_epochs=30, dataset="real", data_dir=None, checkpoint=None):
    # Set seed for deterministic results
    set_seed(42)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Using device: {device}")

    # Define and create the output directory for model checkpoints
    checkpoint_dir = os.path.join(PYTORCH_DIR, "saved_checkpoints")
    os.makedirs(checkpoint_dir, exist_ok=True)

    # Load fixed [6, 256] windows; shuffle training only.
    default_data_dir, file_prefix = DATASET_CONFIGS[dataset]
    data_dir = data_dir or default_data_dir
    train_dataset = NPZIMUDataset(os.path.join(data_dir, f"{file_prefix}_train.npz"))
    val_dataset = NPZIMUDataset(os.path.join(data_dir, f"{file_prefix}_val.npz"))
    gesture_map = dict(enumerate(train_dataset.class_names))
    checkpoint_name = f"gesture_1dcnn_{dataset}_100hz_256_best.pth"

    num_classes = len(gesture_map)
    if val_dataset.class_names != train_dataset.class_names:
        raise ValueError("Training and validation datasets have different classes")

    train_loader = DataLoader(train_dataset, batch_size=32, shuffle=True)
    val_loader = DataLoader(val_dataset, batch_size=32, shuffle=False)

    print("Classes:", gesture_map)

    model = Gesture1DCNN(in_channels=6, num_classes=num_classes).to(device)
    # Inverse-frequency weights give each gesture equal importance in the loss.
    counts = torch.bincount(train_dataset.labels, minlength=num_classes).float()
    if torch.any(counts == 0):
        raise ValueError(f"Training data is missing a class: {counts.tolist()}")
    class_weights = len(train_dataset) / (num_classes * counts)
    criterion = nn.CrossEntropyLoss(weight=class_weights.to(device))
    print("Class counts:", counts.to(torch.int64).tolist())
    print("Loss weights:", [round(value, 4) for value in class_weights.tolist()])
    optimizer = optim.Adam(model.parameters(), lr=1e-3, weight_decay=1e-4)

    best_val_balanced_acc = 0.0
    best_val_loss = float('inf')
    best_model_path = checkpoint or os.path.join(checkpoint_dir, checkpoint_name)
    os.makedirs(os.path.dirname(os.path.abspath(best_model_path)), exist_ok=True)
    train_losses = []
    val_losses = []

    print("\n--- Starting Model Training ---")
    for epoch in range(1, num_epochs + 1):
        # Training Phase
        model.train()
        total_loss, correct, total = 0.0, 0, 0
        for inputs, targets in train_loader:
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
        ax.set_title(f"{dataset.upper()} training and validation loss")
        ax.legend()
        ax.grid(True, alpha=0.3)
        fig.tight_layout()
        plot_path = os.path.join(SCRIPT_DIR, f"gesture_1dcnn_{dataset}_loss.png")
        fig.savefig(plot_path)
        plt.close(fig)
        print(f"Loss plot saved to '{plot_path}'")

    print("\n--- Training Complete ---")
    print(f"Best model saved to '{best_model_path}' with Validation Balanced Accuracy: {best_val_balanced_acc:.2f}%")


def parse_args():
    parser = argparse.ArgumentParser(description="Train the gesture 1D CNN")
    parser.add_argument("--epochs", type=int, default=30)
    parser.add_argument("--dataset", choices=DATASET_CONFIGS, default="real")
    parser.add_argument("--data-dir", default=None,
                        help="override the selected dataset processed directory")
    parser.add_argument("--checkpoint", default=None)
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run_pipeline(args.epochs, args.dataset, args.data_dir, args.checkpoint)
