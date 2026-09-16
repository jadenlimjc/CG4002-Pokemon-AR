"""Convert selected UTD-MHAD inertial trials into CNN-ready NPZ splits.

The output arrays use X=[samples, channels, timesteps] and y=[samples].
Splitting is participant-based to prevent recordings from the same person
appearing in both training and evaluation data.
"""

import argparse
import re
from pathlib import Path

import numpy as np
from scipy.io import loadmat


WINDOW_SIZE = 128
CHANNEL_NAMES = np.array(
    ["acc_x", "acc_y", "acc_z", "gyro_x", "gyro_y", "gyro_z"]
)

# Class zero combines deliberate, non-target wrist movements. It is a proxy
# negative class, not genuine stationary/idle data. Actions 22-27 are excluded
# because UTD-MHAD recorded those with the sensor on the thigh.
OTHER_ACTIONS = {3, 4, 8, 9, 10, 11, 12, 14, 15, 16, 17, 18, 19, 20, 21}
TARGET_ACTIONS = {
    1: "Swipe Left",
    2: "Swipe Right",
    5: "Right-arm Throw",
    6: "Cross Arms",
    7: "Basketball Shoot",
    13: "Front Boxing",
}
CLASS_NAMES = np.array(["Other / Non-target", *TARGET_ACTIONS.values()])

SPLIT_SUBJECTS = {
    "train": {1, 2, 3, 4, 5, 6},
    "val": {7},
    "test": {8},
}

FILENAME_PATTERN = re.compile(
    r"^a(?P<action>\d+)_s(?P<subject>\d+)_t(?P<trial>\d+)_inertial\.mat$",
    re.IGNORECASE,
)


def resample_linear(signal, output_length=WINDOW_SIZE):
    """Linearly resample a [time, channel] trial to a fixed time length."""
    if signal.shape[0] < 2:
        raise ValueError("A trial needs at least two timesteps")
    source_time = np.linspace(0.0, 1.0, signal.shape[0])
    target_time = np.linspace(0.0, 1.0, output_length)
    result = np.empty((output_length, signal.shape[1]), dtype=np.float32)
    for channel in range(signal.shape[1]):
        result[:, channel] = np.interp(
            target_time, source_time, signal[:, channel]
        )
    return result


def load_window(path):
    """Load, validate, normalize and resample one UTD-MHAD trial."""
    contents = loadmat(path)
    if "d_iner" not in contents:
        raise ValueError(f"{path.name} does not contain 'd_iner'")

    signal = np.asarray(contents["d_iner"], dtype=np.float32)
    if signal.ndim != 2:
        raise ValueError(f"{path.name}: expected a 2-D array, got {signal.shape}")
    if signal.shape[1] != 6 and signal.shape[0] == 6:
        signal = signal.T
    if signal.shape[1] != 6:
        raise ValueError(f"{path.name}: expected six channels, got {signal.shape}")
    if not np.isfinite(signal).all():
        raise ValueError(f"{path.name}: data contains NaN or infinity")

    # UTD-MHAD sensor ranges are +/-8 g and +/-1000 degrees/s. Scaling by
    # those physical ranges keeps both channel groups near [-1, 1] and avoids
    # overflowing the accelerator's ap_fixed<16, 6> input representation.
    signal[:, :3] /= 8.0
    signal[:, 3:] /= 1000.0

    # Model/HLS convention is channel-major [6, 128].
    return resample_linear(signal).T


def find_split(subject):
    matches = [name for name, subjects in SPLIT_SUBJECTS.items() if subject in subjects]
    if len(matches) != 1:
        raise ValueError(f"Subject {subject} belongs to {len(matches)} splits")
    return matches[0]


def convert(input_dir, output_dir):
    action_to_label = {action_id: 0 for action_id in OTHER_ACTIONS}
    action_to_label.update(
        {action_id: label for label, action_id in enumerate(TARGET_ACTIONS, start=1)}
    )
    records = {name: [] for name in SPLIT_SUBJECTS}

    for path in sorted(input_dir.glob("*.mat")):
        match = FILENAME_PATTERN.match(path.name)
        if not match:
            print(f"Skipping unrecognized filename: {path.name}")
            continue
        action = int(match.group("action"))
        if action not in action_to_label:
            continue
        subject = int(match.group("subject"))
        trial = int(match.group("trial"))
        split = find_split(subject)
        records[split].append(
            (load_window(path), action_to_label[action], subject, trial, path.name)
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    for split, split_records in records.items():
        if not split_records:
            raise RuntimeError(f"No samples were found for the {split} split")
        windows, labels, subjects, trials, filenames = zip(*split_records)
        x = np.stack(windows).astype(np.float32)
        y = np.asarray(labels, dtype=np.int64)
        destination = output_dir / f"utd_mhad_{split}.npz"
        np.savez_compressed(
            destination,
            X=x,
            y=y,
            subjects=np.asarray(subjects, dtype=np.int64),
            trials=np.asarray(trials, dtype=np.int64),
            filenames=np.asarray(filenames),
            class_names=CLASS_NAMES,
            # String metadata avoids object arrays that require allow_pickle.
            source_action_ids=np.array(
                [",".join(map(str, sorted(OTHER_ACTIONS))),
                 *[str(action) for action in TARGET_ACTIONS]]
            ),
            channel_names=CHANNEL_NAMES,
        )

        counts = np.bincount(y, minlength=len(CLASS_NAMES))
        print(f"{split:>5}: X={x.shape}, y={y.shape}, counts={counts.tolist()}")
        print(f"       range=[{x.min():.6f}, {x.max():.6f}] -> {destination}")


def parse_args():
    script_dir = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=script_dir / "Inertial",
        help="Directory containing *_inertial.mat files",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=script_dir / "utd_mhad_processed",
        help="Directory for generated NPZ splits",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    if not args.input.is_dir():
        raise FileNotFoundError(f"Input directory not found: {args.input}")
    convert(args.input.resolve(), args.output.resolve())


if __name__ == "__main__":
    main()
