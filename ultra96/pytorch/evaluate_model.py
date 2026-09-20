import torch
from torch.utils.data import DataLoader
import numpy as np
import matplotlib.pyplot as plt
from sklearn.metrics import classification_report, confusion_matrix
import seaborn as sns
import argparse
import os

from model import Gesture1DCNN
from train_baseline import DummyIMUDataset, NPZIMUDataset, UTD_DATA_DIR, set_seed

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

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

    cm = confusion_matrix(all_targets, all_preds, labels=range(len(class_map)))
    accuracy = 100.0 * np.sum(np.diag(cm)) / np.sum(cm)
    recalls = np.diag(cm) / np.maximum(cm.sum(axis=1), 1)
    balanced_accuracy = 100.0 * np.mean(recalls)
    print(f"Overall Test Accuracy: {accuracy:.2f}%")
    print(f"Balanced Test Accuracy: {balanced_accuracy:.2f}%")
    print(classification_report(
        all_targets, all_preds, labels=range(len(class_map)),
        target_names=list(class_map.values()), zero_division=0
    ))

    plt.figure(figsize=(12, 8))
    sns.heatmap(cm, annot=True, fmt='d', cmap='Blues', 
                xticklabels=class_map.values(), yticklabels=class_map.values())
    plt.xlabel('Predicted Label')
    plt.ylabel('True Label')
    plt.title(
        f'Confusion Matrix (Accuracy: {accuracy:.2f}%, '
        f'Balanced: {balanced_accuracy:.2f}%)'
    )
    plt.tight_layout()
    plt.savefig(filename, bbox_inches="tight")
    print(f"Saved confusion matrix to '{filename}'")

def main(dataset_name="utd"):
    """
    Main function to load the best model and evaluate its performance.
    """
    set_seed(42)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    
    # --- Configuration ---
    checkpoint_dir = os.path.join(SCRIPT_DIR, "saved_checkpoints")
    if dataset_name == "utd":
        best_model_path = os.path.join(
            checkpoint_dir, "gesture_1dcnn_utd_mhad_100hz_256_best.pth"
        )
        test_dataset = NPZIMUDataset(
            os.path.join(UTD_DATA_DIR, "utd_mhad_test.npz")
        )
        gesture_map = dict(enumerate(test_dataset.class_names))
        output_path = os.path.join(SCRIPT_DIR, "utd_mhad_confusion_matrix.png")
    else:
        best_model_path = os.path.join(
            checkpoint_dir, "gesture_1dcnn_100hz_256_best.pth"
        )
        test_dataset = DummyIMUDataset(
            num_samples=300, window_size=256, num_classes=7, seed=123
        )
        gesture_map = {
            0: "Neutral", 1: "Aim", 2: "Throw", 3: "Stop Aim",
            4: "Punch", 5: "Downward Swipe", 6: "Guard"
        }
        output_path = os.path.join(SCRIPT_DIR, "confusion_matrix.png")
    test_loader = DataLoader(test_dataset, batch_size=32, shuffle=False)

    # --- Load Model ---
    if not os.path.exists(best_model_path):
        print(f"Error: Model checkpoint not found at '{best_model_path}'")
        print("Please run train_baseline.py first to generate the model.")
        return

    print(f"Loading best model from '{best_model_path}' for evaluation...")
    model = Gesture1DCNN(in_channels=6, num_classes=len(gesture_map)).to(device)
    model.load_state_dict(torch.load(best_model_path, map_location=device))

    # --- Evaluate ---
    evaluate_and_generate_confusion_matrix(
        model, test_loader, device, gesture_map, filename=output_path
    )

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Evaluate the gesture 1D CNN")
    parser.add_argument("--dataset", choices=("utd", "synthetic"), default="utd")
    args = parser.parse_args()
    main(args.dataset)
