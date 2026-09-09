import torch
from torch.utils.data import DataLoader
import numpy as np
import matplotlib.pyplot as plt
from sklearn.metrics import confusion_matrix
import seaborn as sns
import os

from model import Gesture1DCNN
from train_baseline import DummyIMUDataset, set_seed

def evaluate_and_generate_confusion_matrix(model, data_loader, device, class_map, filename="confusion_matrix.png"):
    """
    Evaluates the model on the given dataset and generates a confusion matrix.
    This is the definitive way to assess classification performance.
    """
    print("\n--- Generating Confusion Matrix ---")
    model.eval()
    all_preds = []
    all_targets = []

    with torch.no_grad():
        for inputs, targets in data_loader:
            inputs, targets = inputs.to(device), targets.to(device)
            outputs = model(inputs)
            _, predicted = outputs.max(1)
            all_preds.extend(predicted.cpu().numpy())
            all_targets.extend(targets.cpu().numpy())

    cm = confusion_matrix(all_targets, all_preds)
    accuracy = 100.0 * np.sum(np.diag(cm)) / np.sum(cm)
    print(f"Overall Validation Accuracy: {accuracy:.2f}%")

    plt.figure(figsize=(10, 8))
    sns.heatmap(cm, annot=True, fmt='d', cmap='Blues', 
                xticklabels=class_map.values(), yticklabels=class_map.values())
    plt.xlabel('Predicted Label')
    plt.ylabel('True Label')
    plt.title(f'Confusion Matrix (Accuracy: {accuracy:.2f}%)')
    plt.savefig(filename)
    print(f"Saved confusion matrix to '{filename}'")

def main():
    """
    Main function to load the best model and evaluate its performance.
    """
    set_seed(42)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    
    # --- Configuration ---
    checkpoint_dir = "saved_checkpoints"
    best_model_path = os.path.join(checkpoint_dir, "gesture_1dcnn_best.pth")

    gesture_map = {
        0: "Neutral", 1: "Aim", 2: "Throw", 3: "Stop Aim",
        4: "Punch", 5: "Downward Swipe", 6: "Guard"
    }

    # --- Load Data ---
    # Use the same seed for the validation dataset to ensure consistency
    val_dataset = DummyIMUDataset(num_samples=300, window_size=128, num_classes=7, seed=123)
    val_loader = DataLoader(val_dataset, batch_size=32, shuffle=False)

    # --- Load Model ---
    if not os.path.exists(best_model_path):
        print(f"Error: Model checkpoint not found at '{best_model_path}'")
        print("Please run train_baseline.py first to generate the model.")
        return

    print(f"Loading best model from '{best_model_path}' for evaluation...")
    model = Gesture1DCNN(in_channels=6, num_classes=7).to(device)
    model.load_state_dict(torch.load(best_model_path))

    # --- Evaluate ---
    evaluate_and_generate_confusion_matrix(model, val_loader, device, gesture_map)

if __name__ == "__main__":
    main()