import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import Dataset, DataLoader
import matplotlib.pyplot as plt
import argparse
import os, numpy as np
from model import Gesture1DCNN # Import the model from its dedicated file

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
UTD_DATA_DIR = os.path.normpath(os.path.join(
    SCRIPT_DIR, "..", "online_data", "UTD-MHAD_HumanActionRecognitionDataset",
    "utd_mhad_processed"
))

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

# =====================================================================
# 1. SYNTHETIC IMU DATASET GENERATOR
# =====================================================================
class DummyIMUDataset(Dataset):
    """
    Generates synthetic 6-channel IMU time-series data:
    Channels: [acc_x, acc_y, acc_z, gyro_x, gyro_y, gyro_z]
    Tensor Shape: (Channels=6, Window_Length=128)
    """
    def __init__(self, num_samples=1000, window_size=128, num_classes=7, seed=None):
        # Gesture Mapping:
        # 0: Neutral (Idle)
        # 1: Aim
        # 2: Throw
        # 3: Stop Aim
        # 4: Punch
        # 5: Downward Swipe
        # 6: Guard

        self.num_samples = num_samples
        self.window_size = window_size
        self.num_classes = num_classes
        if seed is not None:
            np.random.seed(seed)

        self.data = []
        self.labels = []

        for i in range(num_samples):
            label = np.random.randint(0, num_classes)
            
            # --- Introduce "confounder" gestures ---
            # 25% of the time that a "Neutral" sample is generated, replace it
            # with a random, sharp, non-classifiable movement.
            if label == 0 and np.random.rand() < 0.25:
                label = -1 # Use a temporary label for confounder gestures
            
            sample = self._generate_gesture_sample(label)
            self.data.append(sample)
            # Map the temporary confounder label (-1) back to the Neutral class (0) for training.
            self.labels.append(0 if label == -1 else label)

        self.data = torch.tensor(np.array(self.data), dtype=torch.float32)
        self.labels = torch.tensor(self.labels, dtype=torch.long)

    def _generate_gesture_sample(self, label):
        """Helper to generate a sample for a specific gesture label."""
        sample = np.zeros((6, self.window_size), dtype=np.float32)

        # --- ENHANCEMENT: Add realistic sensor bias and drift ---
        for i in range(6):
            # 1. Add random gaussian noise
            noise_level = np.random.uniform(0.05, 0.2)
            sample[i] = np.random.normal(0, noise_level, self.window_size)
            # 2. Add a random DC offset (bias)
            bias = np.random.normal(0, 0.05)
            sample[i] += bias
            # 3. Add a slight linear drift
            drift = np.linspace(0, np.random.normal(0, 0.03), self.window_size)
            sample[i] += drift

        if label == 0: # Neutral / Idle (pure noise)
            return sample

        if label == -1: # Confounder Gesture (random spikes)
            num_spikes = np.random.randint(1, 4)
            for _ in range(num_spikes):
                channel = np.random.randint(0, 6)
                position = np.random.randint(20, self.window_size - 20)
                width = np.random.uniform(0.1, 0.4)
                amplitude = np.random.uniform(1.0, 3.0) * (1 if np.random.rand() > 0.5 else -1)
                sample[channel, :] += amplitude * np.exp(-((np.arange(self.window_size) - position) / (width * 20))**2)
            return sample

        # Define a time axis for the gesture event
        # --- ADDING REALISM: Random time shift for the gesture ---
        time_shift = np.random.randint(-self.window_size // 3, self.window_size // 3)
        # --- ADDING REALISM: Variable gesture duration ---
        duration = np.random.randint(50, 80)
        start_idx = max(0, self.window_size // 2 - duration // 2 + time_shift)
        end_idx = min(self.window_size, start_idx + duration)
        gesture_len = end_idx - start_idx

        # --- Define Gesture Profiles ---
        std_variation = np.random.uniform(0.8, 1.2)
        spike = lambda amp, std: amp * np.exp(-t**2 / (2 * (std * std_variation)**2))
        smooth_curve = lambda amp, period: amp * np.sin(t / (period * std_variation)) * (t > 0) * (t < np.pi * period * std_variation)
        
        # --- ENHANCEMENT: More complex punch profile with recoil ---
        punch_recoil = lambda amp, std: (amp * np.exp(-t**2 / (2 * (std * std_variation)**2))) - (amp*0.4 * np.exp(-(t-std*2)**2 / (2 * (std*0.8 * std_variation)**2)))

        # --- ADDING REALISM: Random amplitude scaling ---
        amp_scale = np.random.uniform(0.8, 1.2)

        # Apply gesture to a slice of the warped time points
        t = np.linspace(-5, 5, gesture_len)

        if label == 1: # Aim: Arm back and up
            sample[0, start_idx:end_idx] -= spike(1.5 * amp_scale, 0.8)  # Accel X (back)
            sample[2, start_idx:end_idx] += spike(1.2 * amp_scale, 0.8)  # Accel Z (up)
        elif label == 2: # Throw: Forward propulsion after Aim
            sample[0, start_idx:end_idx] += spike(2.5 * amp_scale, 0.4)  # Strong Accel X (forward)
            sample[4, start_idx:end_idx] += spike(2.0 * amp_scale, 0.4)  # Gyro Y (rotation)
            sample[2, start_idx:end_idx] += spike(0.5 * amp_scale, 0.8)  # Minor upward accel
        elif label == 3: # Stop Aim: Return to neutral
            sample[0, start_idx:end_idx] += spike(1.0 * amp_scale, 1.0)  # Accel X (forward to neutral)
            sample[2, start_idx:end_idx] -= spike(1.0 * amp_scale, 1.0)  # Accel Z (down to neutral)
        elif label == 4: # Punch: Fast forward fist
            sample[0, start_idx:end_idx] += punch_recoil(3.0 * amp_scale, 0.3)  # Sharp Accel X with recoil
            sample[4, start_idx:end_idx] += spike(0.4 * amp_scale, 0.5)  # Minor rotational element
        elif label == 5: # Downward Swipe: Rapid downward hand movement
            sample[2, start_idx:end_idx] -= spike(2.8 * amp_scale, 0.4)  # Strong Accel Z (downward)
        elif label == 6: # Guard: Arm crosses chest
            sample[1, start_idx:end_idx] += smooth_curve(1.8 * amp_scale, 2.0)  # Accel Y (lateral)
            sample[5, start_idx:end_idx] += smooth_curve(1.5 * amp_scale, 2.0)  # Gyro Z (twist)

        # --- Augmentation: Time Warping ---
        time_points = np.linspace(-5, 5, self.window_size)
        time_warp_factor = np.random.uniform(0.8, 1.2)
        warped_time_points = time_points * time_warp_factor

        # Interpolate the gesture onto the warped time grid to create the final sample
        final_sample = np.zeros_like(sample)
        for i in range(6):
            final_sample[i] = np.interp(time_points, warped_time_points, sample[i])
        return final_sample

    def __len__(self):
        return self.num_samples

    def __getitem__(self, idx):
        return self.data[idx], self.labels[idx]


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
        if self.data.ndim != 3 or tuple(self.data.shape[1:]) != (6, 128):
            raise ValueError(f"{path}: X must have shape [N, 6, 128]")
        if self.labels.shape != (len(self.data),):
            raise ValueError(f"{path}: y must have one label per window")

    def __len__(self):
        return len(self.data)

    def __getitem__(self, idx):
        return self.data[idx], self.labels[idx]


# =====================================================================
# 3. REAL-TIME POST-PROCESSING (CONFIDENCE & DEBOUNCE FILTER)
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
        window_tensor shape: (1, 6, 128)
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
# 4. TRAINING & VALIDATION PIPELINE
# =====================================================================
def run_pipeline(dataset_name="utd", num_epochs=30):
    # Set seed for deterministic results
    set_seed(42)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Using device: {device}")

    # Define and create the output directory for model checkpoints
    checkpoint_dir = os.path.join(SCRIPT_DIR, "saved_checkpoints")
    os.makedirs(checkpoint_dir, exist_ok=True)

    # Datasets and Loaders
    if dataset_name == "utd":
        train_dataset = NPZIMUDataset(os.path.join(UTD_DATA_DIR, "utd_mhad_train.npz"))
        val_dataset = NPZIMUDataset(os.path.join(UTD_DATA_DIR, "utd_mhad_val.npz"))
        gesture_map = dict(enumerate(train_dataset.class_names))
        checkpoint_name = "gesture_1dcnn_utd_mhad_best.pth"
    else:
        train_dataset = DummyIMUDataset(num_samples=1200, window_size=128, num_classes=7, seed=42)
        val_dataset = DummyIMUDataset(num_samples=300, window_size=128, num_classes=7, seed=123)
        gesture_map = {
            0: "Neutral", 1: "Aim", 2: "Throw", 3: "Stop Aim",
            4: "Punch", 5: "Downward Swipe", 6: "Guard"
        }
        checkpoint_name = "gesture_1dcnn_best.pth"

    num_classes = len(gesture_map)
    if dataset_name == "utd" and val_dataset.class_names != train_dataset.class_names:
        raise ValueError("Training and validation datasets have different classes")

    train_loader = DataLoader(train_dataset, batch_size=32, shuffle=True)
    val_loader = DataLoader(val_dataset, batch_size=32, shuffle=False)

    print("Classes:", gesture_map)

    model = Gesture1DCNN(in_channels=6, num_classes=num_classes).to(device)
    if dataset_name == "utd":
        counts = torch.bincount(train_dataset.labels, minlength=num_classes).float()
        if torch.any(counts == 0):
            raise ValueError(f"Training data is missing a class: {counts.tolist()}")
        class_weights = len(train_dataset) / (num_classes * counts)
        criterion = nn.CrossEntropyLoss(weight=class_weights.to(device))
        print("Class counts:", counts.to(torch.int64).tolist())
        print("Loss weights:", [round(value, 4) for value in class_weights.tolist()])
    else:
        criterion = nn.CrossEntropyLoss()
    optimizer = optim.Adam(model.parameters(), lr=1e-3, weight_decay=1e-4)

    best_val_balanced_acc = 0.0
    best_val_loss = float('inf')
    best_model_path = os.path.join(checkpoint_dir, checkpoint_name)

    print("\n--- Starting Model Training ---")
    for epoch in range(1, num_epochs + 1):
        # Training Phase
        model.train()
        total_loss, correct, total = 0.0, 0, 0
        for inputs, targets in train_loader:
            inputs, targets = inputs.to(device), targets.to(device)

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

        # Validation Phase
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
        print(f"Epoch [{epoch:02d}/{num_epochs:02d}] | Train Loss: {train_loss:.4f} | Train Acc: {train_acc:.2f}% | Val Loss: {avg_val_loss:.4f} | Val Acc: {val_acc:.2f}% | Val Balanced Acc: {val_balanced_acc:.2f}%", end="")

        # The UTD negative class is much larger, so select checkpoints using
        # mean per-class recall rather than imbalance-sensitive raw accuracy.
        if (val_balanced_acc > best_val_balanced_acc or
                (val_balanced_acc == best_val_balanced_acc and
                 avg_val_loss < best_val_loss)):
            best_val_balanced_acc = val_balanced_acc
            best_val_loss = avg_val_loss
            torch.save(model.state_dict(), best_model_path)
            print(f"  -> New best model saved to {best_model_path} (Val Balanced Acc: {best_val_balanced_acc:.2f}%, Val Loss: {best_val_loss:.4f})")
        else:
            print() # Newline if no model was saved

    print("\n--- Training Complete ---")
    print(f"Best model saved to '{best_model_path}' with Validation Balanced Accuracy: {best_val_balanced_acc:.2f}%")


def parse_args():
    parser = argparse.ArgumentParser(description="Train the gesture 1D CNN")
    parser.add_argument("--dataset", choices=("utd", "synthetic"), default="utd")
    parser.add_argument("--epochs", type=int, default=30)
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run_pipeline(args.dataset, args.epochs)
