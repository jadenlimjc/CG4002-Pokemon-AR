"""Evaluate a trained software model on the default test split or --data NPZ.

Example from the repository root:
    python ultra96/pytorch/training/evaluate_model.py --data \
        ultra96/real_data/processed_50hz_128/jaden_recordings_22_oct__yiyang_recordings_22_oct_test.npz

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
import json
import os
import sys
from pathlib import Path

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from ultra96.pytorch.training.model import Gesture1DCNN
from ultra96.pytorch.training.cross_validate_loso import (
    STATE_CLASS_IDS, single_head_config, state_evaluation_batches, state_evaluation_metrics,
)
from ultra96.pytorch.training.train_baseline import (
    DATASET_CONFIGS, NPZIMUDataset, set_seed, SAMPLE_RATE_HZ, WINDOW_SIZE, run_label, resolve_software_checkpoint,
)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PYTORCH_DIR = os.path.dirname(SCRIPT_DIR)

def evaluate_and_generate_confusion_matrix(model, data_loader, device, class_map, filename="confusion_matrix.png"):
    """Report state-masked single-head predictions and preserve unrestricted scores."""
    label = run_label(data_loader.dataset.sample_rate, data_loader.dataset.window_size)
    names = list(class_map.values())
    model.eval()
    unrestricted_cm = np.zeros((len(names), len(names)), dtype=np.int64)
    state_cms, by_state = {}, {}
    with torch.no_grad():
        for inputs, targets in data_loader:
            inputs, targets = inputs.to(device), targets.to(device)
            logits = model(inputs)
            np.add.at(unrestricted_cm, (targets.cpu().numpy(), logits.argmax(1).cpu().numpy()), 1)
            for state, masked, selected_targets, _ in state_evaluation_batches(logits, targets, names):
                predictions = masked.argmax(1).cpu().numpy()
                selected_targets = selected_targets.cpu().numpy()
                cm = state_cms.setdefault(state, np.zeros_like(unrestricted_cm))
                np.add.at(cm, (selected_targets, predictions), 1)
                predicted, actual = by_state.setdefault(state, ([], []))
                predicted.extend(predictions.tolist())
                actual.extend(selected_targets.tolist())
    result = state_evaluation_metrics(state_cms, unrestricted_cm, names)
    print(f"\nEvaluation: {result['evaluation_mode']} | {label}")
    print(result["evaluation_context"])
    print(f"State-masked balanced accuracy: {result['balanced_accuracy']:.2f}%")
    print(f"Unrestricted balanced accuracy: {result['unrestricted']['balanced_accuracy']:.2f}%")
    figure, axes = plt.subplots(1, len(state_cms), figsize=(9 * len(state_cms), 8), squeeze=False)
    for ax, (state, full_cm) in zip(axes[0], state_cms.items()):
        ids = list(STATE_CLASS_IDS[state]) if state in STATE_CLASS_IDS else list(range(len(names)))
        state_names = [names[i] for i in ids]
        cm = full_cm[np.ix_(ids, ids)]
        metrics = result['states'][state]
        predictions, targets = by_state[state]
        print(f"{state.title()} state: accuracy={metrics['accuracy']:.2f}%, balanced={metrics['balanced_accuracy']:.2f}%")
        print(classification_report(targets, predictions, labels=ids, target_names=state_names, zero_division=0))
        sns.heatmap(cm, annot=True, fmt="d", cmap="Blues", ax=ax, xticklabels=state_names, yticklabels=state_names)
        ax.set(xlabel="Predicted Label", ylabel="True Label",
               title=f"{state.title()} state | accuracy {metrics['accuracy']:.2f}% | balanced {metrics['balanced_accuracy']:.2f}%")
    figure.suptitle(f"{label} | {result['evaluation_mode']}\n{result['evaluation_context']}")
    figure.tight_layout()
    figure.savefig(filename, bbox_inches="tight")
    plt.close(figure)
    Path(filename).with_suffix(".json").write_text(json.dumps(result, indent=2) + "\n")
    print(f"Saved evaluation image and JSON to '{filename}'")
    return result

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
    sample_rate = getattr(args, "sample_rate", SAMPLE_RATE_HZ)
    window_size = getattr(args, "window_size", WINDOW_SIZE)
    test_dataset = NPZIMUDataset(test_path, sample_rate, window_size)
    if not len(test_dataset):
        raise ValueError(f"{test_path}: evaluation dataset is empty")
    # The UTD preprocessor records its proxy actions in this metadata field.
    # Inspect the file contents so renamed UTD NPZs also select UTD weights.
    with np.load(test_path) as data:
        dataset_name = "utd" if "source_action_ids" in data else "real"
    best_model_path = args.checkpoint or resolve_software_checkpoint(dataset_name, sample_rate, window_size)
    gesture_map = dict(enumerate(test_dataset.class_names))
    output_path = args.output or os.path.join(
        SCRIPT_DIR, f"{file_prefix}_{sample_rate}hz_{window_size}_confusion_matrix.png")
    test_loader = DataLoader(test_dataset, batch_size=32, shuffle=False)

    # --- Load Model ---
    if not os.path.exists(best_model_path):
        print(f"Error: Model checkpoint not found at '{best_model_path}'")
        print("Please run train_baseline.py first to generate the model.")
        return

    print(f"Loading best model from '{best_model_path}' for evaluation...")
    config_path = Path(best_model_path).with_suffix(".json")
    config = {"in_channels": 6, "num_classes": len(gesture_map)}
    if config_path.is_file():
        metadata = json.loads(config_path.read_text())
        if metadata["class_names"] != test_dataset.class_names:
            raise ValueError("Checkpoint configuration and dataset have different classes")
        for key, expected in (("sample_rate_hz", sample_rate), ("window_size", window_size)):
            if key in metadata and metadata[key] != expected:
                raise ValueError(f"Checkpoint {key}={metadata[key]} does not match requested {expected}")
        config = metadata["model_config"]
        print(f"Loading model configuration from '{config_path}'")
    model = Gesture1DCNN(**single_head_config(config)).to(device)
    model.load_state_dict(torch.load(best_model_path, map_location=device))

    # --- Evaluate ---
    return evaluate_and_generate_confusion_matrix(
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
    parser.add_argument("--output", default=None,
                        help="confusion matrix path; default name includes sample rate and window size")
    parser.add_argument("--sample-rate", type=int, default=SAMPLE_RATE_HZ,
                        help="expected dataset sampling rate in Hz (default: 50)")
    parser.add_argument("--window-size", type=int, default=WINDOW_SIZE,
                        help="expected samples per window, at least 4 (default: 128)")
    args = parser.parse_args()
    if args.sample_rate <= 0 or args.window_size < 4:
        parser.error("--sample-rate must be positive and --window-size must be at least 4")
    return args


if __name__ == "__main__":
    main(parse_args())
