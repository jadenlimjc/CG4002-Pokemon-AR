"""Evaluate a trained software model on the default test split or --data NPZ.

Example from the repository root:
    python ultra96/pytorch/training/evaluate_model.py --data \
        ultra96/real_data/processed/jaden_recordings_22_oct__yiyang_recordings_22_oct_test.npz

Use --checkpoint to choose trained weights and --output to choose the
confusion-matrix image. No training is performed.
Defaults to the real test split. UTD NPZs are identified by their
source_action_ids metadata and select the UTD checkpoint automatically.
"""

import torch
from torch.utils.data import DataLoader
import numpy as np
import matplotlib.pyplot as plt
from sklearn.metrics import classification_report, confusion_matrix
import seaborn as sns
import argparse
import os
import sys
from pathlib import Path

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from ultra96.pytorch.training.model import Gesture1DCNN
from ultra96.pytorch.training.train_baseline import DATASET_CONFIGS, NPZIMUDataset, set_seed

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PYTORCH_DIR = os.path.dirname(SCRIPT_DIR)

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

    # Rows are true classes; columns are predicted classes.
    cm = confusion_matrix(all_targets, all_preds, labels=range(len(class_map)))
    accuracy = 100.0 * np.sum(np.diag(cm)) / np.sum(cm)
    # Balanced accuracy averages recall so every gesture counts equally.
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

def main(args=None):
    """
    Main function to load the best model and evaluate its performance.
    """
    set_seed(42)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    
    # --- Configuration ---
    args = args or parse_args()
    default_data_dir, file_prefix = DATASET_CONFIGS["real"]
    data_dir = args.data_dir or default_data_dir
    test_path = args.data or os.path.join(data_dir, f"{file_prefix}_test.npz")
    print(f"Loading evaluation data from '{test_path}'...")
    test_dataset = NPZIMUDataset(test_path)
    if not len(test_dataset):
        raise ValueError(f"{test_path}: evaluation dataset is empty")
    # The UTD preprocessor records its proxy actions in this metadata field.
    # Inspect the file contents so renamed UTD NPZs also select UTD weights.
    with np.load(test_path) as data:
        dataset_name = "utd" if "source_action_ids" in data else "real"
    best_model_path = args.checkpoint or os.path.join(
        PYTORCH_DIR, "saved_checkpoints",
        f"gesture_1dcnn_{dataset_name}_100hz_256_best.pth"
    )
    gesture_map = dict(enumerate(test_dataset.class_names))
    output_path = args.output
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

def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    data_source = parser.add_mutually_exclusive_group()
    data_source.add_argument("--data", default=None,
                             help="evaluate an NPZ directly; defaults to the real test "
                                  "split, UTD metadata selects UTD weights")
    data_source.add_argument("--data-dir", default=None,
                             help="directory containing real_gestures_test.npz")
    parser.add_argument("--checkpoint", default=None)
    parser.add_argument("--output", default=os.path.join(
        SCRIPT_DIR, "real_gestures_confusion_matrix.png"))
    return parser.parse_args()


if __name__ == "__main__":
    main(parse_args())
