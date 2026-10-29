"""Convert labelled real-sensor CSV recordings into reproducible NPZ splits.

Each CSV is one 100 Hz recording.  A 2.56 second window is centred on the
strongest smoothed motion; neutral recordings use their temporal centre.
An optional timestamp_ms column is accepted and excluded from model inputs.
Training recordings produce small centre-offset variants, while validation
and test recordings produce exactly one window each.  Splits are made by
recording number so variants from one recording can never leak across splits.
The input may be the real_data root, a subject folder, or a dated session.
Sessions may contain incomplete sets after recordings are removed. Remaining
trial numbers retain their original splits; do not renumber cleaned files.
The 60/20/20 split pattern repeats for each block of ten trials, with no
upper limit on the trial number.
Uppercut is the final class (label 10), even when absent from a session.
"""

import argparse
import re
from pathlib import Path

import numpy as np


SAMPLE_RATE_HZ = 100
WINDOW_SIZE = 256
GRAVITY_M_S2 = 9.80665
ACCEL_RANGE_G = 8.0
GYRO_RANGE_DPS = 500.0
CHANNEL_NAMES = np.array(["ax", "ay", "az", "gx", "gy", "gz"])

# Class order must match PyTorch, HLS, and the FPGA output logits.
CLASS_SPECS = (
    ("neutral", "Neutral"),
    ("aim", "Aim"),
    ("stopaim", "Stop Aim"),
    ("throw", "Throw"),
    ("punch", "Punch"),
    ("swipe", "Downward Swipe"),
    ("guard", "Guard"),
    ("uturn", "Flee / U-turn"),
    ("backpocket", "Switch Pokemon / Back-pocket reach"),
    ("frontpocket", "Use Item / Front-pocket reach"),
    ("uppercut", "Uppercut"),
)
CLASS_NAMES = np.asarray([display for _, display in CLASS_SPECS])
PREFIX_TO_LABEL = {prefix: label for label, (prefix, _) in enumerate(CLASS_SPECS)}
FILENAME_PATTERN = re.compile(r"^(?P<prefix>[a-z]+)(?P<trial>\d+)\.csv$", re.I)
# Repeat this pattern for every ten trials; assignments stay stable as data grows.
# Split by recording number so one recording never crosses data splits.
SPLIT_TRIALS = {"train": set(range(1, 7)), "val": {7, 8}, "test": {9, 10}}
# Five training windows span +/-0.64 s at 100 Hz; val/test stay centred.
TRAIN_OFFSETS = (-64, -32, 0, 32, 64)


def split_for_trial(trial):
    if trial < 1:
        raise ValueError(f"trial number must be positive, got {trial}")
    trial_in_block = (trial - 1) % 10 + 1
    matches = [split for split, trials in SPLIT_TRIALS.items()
               if trial_in_block in trials]
    if len(matches) != 1:
        raise ValueError(f"trial {trial} belongs to {len(matches)} splits")
    return matches[0]


def load_csv(path):
    signal = np.genfromtxt(path, delimiter=",", names=True, dtype=np.float32)
    expected_columns = tuple(CHANNEL_NAMES)
    if signal.dtype.names not in (expected_columns, ("timestamp_ms",) + expected_columns):
        raise ValueError(
            f"{path.name}: expected columns {CHANNEL_NAMES.tolist()} "
            f"with an optional leading timestamp_ms column, "
            f"got {signal.dtype.names}"
        )
    matrix = np.column_stack([signal[name] for name in CHANNEL_NAMES]).astype(np.float32)
    if matrix.ndim != 2 or matrix.shape[1] != 6 or len(matrix) < 2:
        raise ValueError(f"{path.name}: expected at least two rows of six channels")
    if not np.isfinite(matrix).all():
        raise ValueError(f"{path.name}: contains NaN or infinity")
    # CSV units are m/s^2 and rad/s. Match live inference and keep fixed-point
    # inputs close to [-1, 1] by expressing them as fractions of sensor range.
    matrix[:, :3] /= ACCEL_RANGE_G * GRAVITY_M_S2
    matrix[:, 3:] /= np.deg2rad(GYRO_RANGE_DPS)
    return matrix


def motion_centre(signal):
    """Centre the window on the strongest smoothed motion."""
    jerk = np.linalg.norm(np.diff(signal[:, :3], axis=0, prepend=signal[:1, :3]), axis=1)
    rotation = np.linalg.norm(signal[:, 3:], axis=1)
    energy = jerk + rotation
    smoothing = np.ones(21, dtype=np.float32) / 21.0
    return int(np.argmax(np.convolve(energy, smoothing, mode="same")))


def extract_window(signal, centre):
    # Produce the fixed [6, 256] model input; edge-pad short boundaries.
    start = int(centre) - WINDOW_SIZE // 2
    end = start + WINDOW_SIZE
    before = max(0, -start)
    after = max(0, end - len(signal))
    clipped = signal[max(0, start):min(len(signal), end)]
    if before or after:
        clipped = np.pad(clipped, ((before, after), (0, 0)), mode="edge")
    if clipped.shape != (WINDOW_SIZE, 6):
        raise AssertionError(f"internal window shape error: {clipped.shape}")
    return clipped.T.astype(np.float32)


def validate_session_recordings(session, seen):
    """Report incomplete sessions without rejecting cleaned recordings."""
    prefixes = {prefix for prefix, _ in CLASS_SPECS}
    if not any(prefix == "uppercut" for prefix, _ in seen):
        prefixes.remove("uppercut")
        print(f"Warning: {session} has no Uppercut recordings")
    expected = {(prefix, trial) for prefix in prefixes for trial in range(1, 11)}
    missing = sorted(expected - seen)
    if missing:
        print(f"Warning: missing recordings in {session} (skipped): {missing}")


def convert(input_dir, output_dir):
    if not input_dir.is_dir():
        raise ValueError(f"input directory does not exist: {input_dir}")
    paths = sorted(
        path for path in input_dir.rglob("*.csv")
        if not path.is_relative_to(output_dir)
    )
    if not paths:
        raise RuntimeError(f"no CSV recordings found in {input_dir}")
    records = {split: [] for split in SPLIT_TRIALS}
    seen_by_session = {}
    for path in paths:
        session = path.parent
        seen = seen_by_session.setdefault(session, set())
        match = FILENAME_PATTERN.match(path.name)
        if not match:
            raise ValueError(f"unrecognized CSV filename: {path.name}")
        prefix = match.group("prefix").lower()
        if prefix not in PREFIX_TO_LABEL:
            raise ValueError(f"unknown gesture prefix in {path.name}: {prefix}")
        trial = int(match.group("trial"))
        key = (prefix, trial)
        if key in seen:
            raise ValueError(f"duplicate gesture/trial in {session}: {key}")
        seen.add(key)
        split = split_for_trial(trial)
        label = PREFIX_TO_LABEL[prefix]
        signal = load_csv(path)
        # Neutral uses the recording centre; gestures use the motion peak.
        base_centre = len(signal) // 2 if prefix == "neutral" else motion_centre(signal)
        offsets = TRAIN_OFFSETS if split == "train" else (0,)
        for offset in offsets:
            records[split].append(
                (extract_window(signal, base_centre + offset), label, trial,
                 path.relative_to(input_dir).as_posix(), offset,
                 session.parent.name, session.name)
            )

    for session, seen in seen_by_session.items():
        validate_session_recordings(session, seen)

    print(f"Loaded {len(paths)} recordings from {len(seen_by_session)} sessions")

    # Fail before writing any files, rather than leaving partially updated
    # splits or allowing downstream training/evaluation on an empty dataset.
    empty_splits = [split for split, items in records.items() if not items]
    if empty_splits:
        raise RuntimeError(
            f"No recordings remain for splits: {empty_splits}. "
            "Keep original trial numbers. In each block of ten trials: "
            "train 1-6, val 7-8, test 9-10 (repeating for 11-20, etc.)."
        )
    for split, items in records.items():
        present = {item[1] for item in items}
        missing_classes = [name for label, name in enumerate(CLASS_NAMES)
                           if label not in present]
        if missing_classes:
            print(f"Warning: {split} has no samples for classes: {missing_classes}")

    output_dir.mkdir(parents=True, exist_ok=True)
    for split, split_records in records.items():
        windows, labels, trials, filenames, offsets, subjects, sessions = zip(*split_records)
        x = np.stack(windows).astype(np.float32)
        y = np.asarray(labels, dtype=np.int64)
        destination = output_dir / f"real_gestures_{split}.npz"
        np.savez_compressed(
            destination, X=x, y=y, class_names=CLASS_NAMES,
            trials=np.asarray(trials, dtype=np.int64),
            filenames=np.asarray(filenames), centre_offsets=np.asarray(offsets),
            subjects=np.asarray(subjects), sessions=np.asarray(sessions),
            channel_names=CHANNEL_NAMES,
            sample_rate_hz=np.asarray(SAMPLE_RATE_HZ),
            window_size=np.asarray(WINDOW_SIZE),
            accel_range_g=np.asarray(ACCEL_RANGE_G, dtype=np.float32),
            gyro_range_dps=np.asarray(GYRO_RANGE_DPS, dtype=np.float32),
            normalization=np.asarray("accel/(8*9.80665), gyro/radians(500)"),
        )
        counts = np.bincount(y, minlength=len(CLASS_NAMES))
        print(f"{split:>5}: X={x.shape}, counts={counts.tolist()}, "
              f"range=[{x.min():.4f}, {x.max():.4f}] -> {destination}")


def parse_args():
    script_dir = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=script_dir,
                        help="Data root, subject folder, or dated session (default: real_data)")
    parser.add_argument("--output", type=Path, default=script_dir / "processed")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    convert(args.input.resolve(), args.output.resolve())
