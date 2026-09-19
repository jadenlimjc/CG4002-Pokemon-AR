"""Convert selected UTD-MHAD inertial trials into game-gesture NPZ splits.

The output arrays use X=[samples, channels, timesteps] and y=[samples].
Splitting is participant-based to prevent recordings from the same person
appearing in both training and evaluation data.

UTD-MHAD does not contain the project's exact gestures, so whole actions are
used as motion proxies. Neutral is intentionally omitted because UTD-MHAD has
no true idle recording.
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

# (project class, UTD action ID, start fraction, end fraction, rationale)
GESTURE_SOURCES = (
    ("Punch", 13, 0.00, 1.00, "Boxing"),
    ("Downward Swipe", 12, 0.00, 1.00, "Bowling"),
    ("Guard", 6, 0.00, 1.00, "Arm cross"),
    ("Flee / U-turn", 14, 0.00, 1.00, "Baseball swing"),
    ("Switch Pokemon / Back-pocket reach", 15, 0.00, 1.00, "Tennis swing"),
    ("Use Item / Front-pocket reach", 16, 0.00, 1.00, "Arm curl"),
    ("Throw", 5, 0.00, 1.00, "Right-arm throw"),
)
CLASS_NAMES = np.array([source[0] for source in GESTURE_SOURCES])

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


def load_signal(path):
    """Load, validate, and normalize one UTD-MHAD trial."""
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

    return signal


def extract_window(signal, start_fraction=0.0, end_fraction=1.0):
    """Crop a normalized temporal phase and return channel-major [6, 128]."""
    if not 0.0 <= start_fraction < end_fraction <= 1.0:
        raise ValueError("Phase fractions must satisfy 0 <= start < end <= 1")
    start = int(np.floor(start_fraction * signal.shape[0]))
    end = int(np.ceil(end_fraction * signal.shape[0]))
    phase = signal[start:end]
    if phase.shape[0] < 2:
        raise ValueError(
            f"Phase [{start_fraction}, {end_fraction}] has too few timesteps"
        )
    # Model/HLS convention is channel-major [6, 128].
    return resample_linear(phase).T


def find_split(subject):
    matches = [name for name, subjects in SPLIT_SUBJECTS.items() if subject in subjects]
    if len(matches) != 1:
        raise ValueError(f"Subject {subject} belongs to {len(matches)} splits")
    return matches[0]


def convert(input_dir, output_dir):
    action_to_sources = {}
    for label, (_, action, start, end, proxy) in enumerate(GESTURE_SOURCES):
        action_to_sources.setdefault(action, []).append((label, start, end, proxy))
    records = {name: [] for name in SPLIT_SUBJECTS}

    for path in sorted(input_dir.glob("*.mat")):
        match = FILENAME_PATTERN.match(path.name)
        if not match:
            print(f"Skipping unrecognized filename: {path.name}")
            continue
        action = int(match.group("action"))
        if action not in action_to_sources:
            continue
        subject = int(match.group("subject"))
        trial = int(match.group("trial"))
        split = find_split(subject)
        signal = load_signal(path)
        for label, start, end, _ in action_to_sources[action]:
            records[split].append(
                (extract_window(signal, start, end), label, subject, trial, path.name)
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
            source_action_ids=np.asarray(
                [str(source[1]) for source in GESTURE_SOURCES]
            ),
            source_action_names=np.asarray(
                [source[4] for source in GESTURE_SOURCES]
            ),
            source_time_ranges=np.asarray(
                [[source[2], source[3]] for source in GESTURE_SOURCES],
                dtype=np.float32,
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
