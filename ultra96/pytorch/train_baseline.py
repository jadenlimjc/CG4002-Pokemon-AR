import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import Dataset, DataLoader
import matplotlib.pyplot as plt
import os
import numpy as np
from model import Gesture1DCNN # Import the model from its dedicated file

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

        for _ in range(num_samples):
            label = np.random.randint(0, num_classes)
            sample = self._generate_gesture_sample(label)
            self.data.append(sample)
            self.labels.append(label)

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

        if label == 0: # Neutral / Idle
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
        return final_sample # BUG FIX: Return the time-warped sample

    def __len__(self):
        return self.num_samples

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
# 4. DATA VISUALIZATION
# =====================================================================
def visualize_and_save_gestures(dataset, gesture_map, filename="gesture_visualization.png"):
    """Finds one sample of each gesture and plots its 6-channel data."""
    print(f"\n--- Generating Data Visualization ---")
    
    # Define the channels for the y-axis labels
    channels = ["Accel X", "Accel Y", "Accel Z", "Gyro X", "Gyro Y", "Gyro Z"]
    
    # Create a figure with one subplot for each gesture type
    fig, axes = plt.subplots(len(gesture_map), 1, figsize=(12, 2 * len(gesture_map)), sharex=True)
    fig.suptitle("Synthetic IMU Gesture Samples", fontsize=16)

    for i, (label, name) in enumerate(gesture_map.items()):
        ax = axes[i]
        try:
            # Find the first index of the current gesture label in the dataset
            sample_idx = next(j for j, lbl in enumerate(dataset.labels) if lbl == label)
            sample_data, _ = dataset[sample_idx]
            sample_data = sample_data.numpy() # Convert from tensor to numpy array

            # Plot all 6 channels for this sample
            for channel_idx in range(sample_data.shape[0]):
                ax.plot(sample_data[channel_idx], label=channels[channel_idx])
            
            ax.set_title(f"Gesture: {name} (Label: {label})")
            ax.set_ylabel("Amplitude")
            ax.grid(True, linestyle='--', alpha=0.6)

        except StopIteration:
            ax.set_title(f"Gesture: {name} (Label: {label}) - Not found in dataset")

    axes[-1].set_xlabel("Time Steps")
    fig.tight_layout(rect=[0, 0.03, 1, 0.97]) # Adjust layout to make room for suptitle
    plt.savefig(filename)
    print(f"Saved gesture visualization to '{filename}'")

# =====================================================================
# 4. TRAINING & VALIDATION PIPELINE
# =====================================================================
def run_pipeline():
    # Set seed for deterministic results
    set_seed(42)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Using device: {device}")

    # Define and create the output directory for model checkpoints
    checkpoint_dir = "saved_checkpoints"
    os.makedirs(checkpoint_dir, exist_ok=True)

    # Datasets and Loaders
    train_dataset = DummyIMUDataset(num_samples=1200, window_size=128, num_classes=7, seed=42)
    val_dataset = DummyIMUDataset(num_samples=300, window_size=128, num_classes=7, seed=123)

    train_loader = DataLoader(train_dataset, batch_size=32, shuffle=True)
    val_loader = DataLoader(val_dataset, batch_size=32, shuffle=False)

    # Gesture mapping for readable output and visualization
    gesture_map = {
        0: "Neutral", 1: "Aim", 2: "Throw", 3: "Stop Aim",
        4: "Punch", 5: "Downward Swipe", 6: "Guard"
    }

    # Visualize the generated validation data before starting training
    visualize_and_save_gestures(val_dataset, gesture_map)

    model = Gesture1DCNN(in_channels=6, num_classes=7).to(device)
    criterion = nn.CrossEntropyLoss()
    optimizer = optim.Adam(model.parameters(), lr=1e-3, weight_decay=1e-4)

    best_val_acc = 0.0
    best_val_loss = float('inf')
    best_model_path = os.path.join(checkpoint_dir, "gesture_1dcnn_best.pth")

    print("\n--- Starting Model Training ---")
    num_epochs = 10
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
        with torch.no_grad():
            for inputs, targets in val_loader:
                inputs, targets = inputs.to(device), targets.to(device)
                outputs = model(inputs)
                loss = criterion(outputs, targets)
                val_loss += loss.item() * inputs.size(0)
                _, predicted = outputs.max(1)
                val_total += targets.size(0)
                val_correct += predicted.eq(targets).sum().item()

        val_acc = 100.0 * val_correct / val_total
        avg_val_loss = val_loss / val_total
        print(f"Epoch [{epoch:02d}/{num_epochs:02d}] | Train Loss: {train_loss:.4f} | Train Acc: {train_acc:.2f}% | Val Loss: {avg_val_loss:.4f} | Val Acc: {val_acc:.2f}%", end="")

        # Save the model if validation accuracy improves, or if accuracy is the same but loss decreases
        if val_acc > best_val_acc or (val_acc == best_val_acc and avg_val_loss < best_val_loss):
            best_val_acc = val_acc
            best_val_loss = avg_val_loss
            torch.save(model.state_dict(), best_model_path)
            print(f"  -> New best model saved to {best_model_path} (Val Acc: {best_val_acc:.2f}%, Val Loss: {best_val_loss:.4f})")
        else:
            print() # Newline if no model was saved

    # =====================================================================
    # 5. TEST REAL-TIME DEBOUNCE INFERENCE
    # =====================================================================
    # Load the best model for the final test
    print("\n--- Testing Real-Time Predictor with Debounce ---")
    print(f"Loading best model from '{best_model_path}' for testing (Best Val Acc: {best_val_acc:.2f}%, Best Val Loss: {best_val_loss:.4f})")
    model.load_state_dict(torch.load(best_model_path))

    # Create the predictor AFTER loading the best model weights
    predictor = RealTimeGesturePredictor(model.cpu(),
                                       confidence_threshold=0.70,
                                       debounce_cooldown_steps=3,
                                       idle_class_idx=0,
                                       class_map=gesture_map)

    # --- Create a more realistic test stream from the validation set ---
    # Find one sample of a gesture (e.g., class 4 - Punch) and one of idle (class 0)
    try:
        gesture_sample, _ = val_dataset[next(i for i, label in enumerate(val_dataset.labels) if label == 4)] # Find first instance of label 4
        idle_sample, _ = val_dataset[next(i for i, label in enumerate(val_dataset.labels) if label == 0)]    # Find first instance of label 0
    except StopIteration:
        print("Could not find required gesture/idle samples in the validation set for the test stream.")
        # Fallback to creating a random sample if not found
        # This is a fallback and might not be representative of the validation set.
        # The 'try' block is the preferred path.
        gesture_sample = torch.from_numpy(val_dataset._generate_gesture_sample(4))
        idle_sample = torch.from_numpy(val_dataset._generate_gesture_sample(0))

    # Simulate a stream: [idle, idle, GESTURE, GESTURE, idle, idle] to test the debouncer
    # Ensure all samples in the stream are tensors, regardless of where they came from.
    if not isinstance(gesture_sample, torch.Tensor):
        gesture_sample = torch.from_numpy(gesture_sample)
    if not isinstance(idle_sample, torch.Tensor):
        idle_sample = torch.from_numpy(idle_sample)
        
    test_stream = [idle_sample, idle_sample, gesture_sample, gesture_sample, idle_sample, idle_sample]

    print("Simulating stream: [IDLE, IDLE, PUNCH, PUNCH, IDLE, IDLE]")
    for step, sample in enumerate(test_stream, 1):
        # Add a batch dimension: (6, 128) -> (1, 6, 128)
        window_tensor = sample.unsqueeze(0)
        pred_gesture, conf, status = predictor.predict_window(window_tensor)
        print(f"Step {step}: Status = {status:<15} | Gesture = {pred_gesture:<14} | Confidence = {conf:.2f}")


if __name__ == "__main__":
    run_pipeline()
