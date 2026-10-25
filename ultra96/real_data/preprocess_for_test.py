"""Build a test-only NPZ from one or more recording session directories.

Run from the repository root:
    python ultra96/real_data/preprocess_for_test.py --input \
        ultra96/real_data/jaden/jaden_recordings_22_oct \
        ultra96/real_data/yiyang/yiyang_recordings_22_oct

Without --output, writes processed/<directory_names_joined_by__>_test.npz
beside this script, e.g.
processed/jaden_recordings_22_oct__yiyang_recordings_22_oct_test.npz.
Directory names follow input order; repeated directory paths appear once.
Use --output to override the destination.

Each input directory must directly contain labelled gesture CSVs, such as
aim1.csv and neutral1.csv. Subdirectories are not scanned. Repeated directory
paths are included only once. Every recording yields one window, regardless
of trial number; no train/validation split or training
offset augmentation is applied. Labels, normalization, and window extraction
match preprocess_for_training.py. Only the supplied sessions are included.
Session metadata uses the directory name; subject metadata uses its parent
directory name. Filenames are relative to the common parent of the inputs.

Pass the generated NPZ directly to the PyTorch evaluator:
    python ultra96/pytorch/training/evaluate_model.py \
        --data \
        ultra96/real_data/processed/jaden_recordings_22_oct__yiyang_recordings_22_oct_test.npz
"""

import argparse
import os
from pathlib import Path

import numpy as np

if __package__:
    from . import preprocess_for_training as preprocessing
else:
    import preprocess_for_training as preprocessing


def convert(input_dirs, output_path=None):
    input_dirs = list(dict.fromkeys(Path(path).resolve() for path in input_dirs))
    if not input_dirs:
        raise ValueError("at least one recording directory is required")
    input_root = Path(os.path.commonpath([str(path.parent) for path in input_dirs]))
    if output_path is None:
        filename = "__".join(path.name for path in input_dirs) + "_test.npz"
        output_path = Path(__file__).resolve().parent / "processed" / filename
    output_path = Path(output_path).resolve()
    if output_path.suffix.lower() != ".npz":
        raise ValueError("output must be an .npz file")

    windows, labels, trials, filenames, subjects, sessions = [], [], [], [], [], []
    for session in input_dirs:
        if not session.is_dir():
            raise ValueError(f"required recording session does not exist: {session}")
        paths = sorted(session.glob("*.csv"))
        if not paths:
            raise ValueError(f"no CSV recordings found in {session}")
        seen = set()
        for path in paths:
            match = preprocessing.FILENAME_PATTERN.fullmatch(path.name)
            if not match:
                raise ValueError(f"unrecognized CSV filename: {path}")
            prefix = match.group("prefix").lower()
            trial = int(match.group("trial"))
            if prefix not in preprocessing.PREFIX_TO_LABEL:
                raise ValueError(f"unknown gesture prefix in {path}: {prefix}")
            if trial < 1:
                raise ValueError(f"trial number must be positive: {path}")
            key = (prefix, trial)
            if key in seen:
                raise ValueError(f"duplicate gesture/trial in {session}: {key}")
            seen.add(key)
            signal = preprocessing.load_csv(path)
            centre = (len(signal) // 2 if prefix == "neutral"
                      else preprocessing.motion_centre(signal))
            windows.append(preprocessing.extract_window(signal, centre))
            labels.append(preprocessing.PREFIX_TO_LABEL[prefix])
            trials.append(trial)
            filenames.append(path.relative_to(input_root).as_posix())
            subjects.append(session.parent.name)
            sessions.append(session.name)
        preprocessing.validate_session_recordings(session, seen)
        print(f"Loaded {len(paths)} recordings from {session}")

    x = np.stack(windows).astype(np.float32)
    y = np.asarray(labels, dtype=np.int64)
    counts = np.bincount(y, minlength=len(preprocessing.CLASS_NAMES))
    missing = preprocessing.CLASS_NAMES[counts == 0].tolist()
    if missing:
        print(f"Warning: test has no samples for classes: {missing}")

    # Write only after all supplied sessions have been loaded and validated.
    output_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        output_path, X=x, y=y, class_names=preprocessing.CLASS_NAMES,
        trials=np.asarray(trials, dtype=np.int64),
        filenames=np.asarray(filenames),
        centre_offsets=np.zeros(len(y), dtype=np.int64),
        subjects=np.asarray(subjects), sessions=np.asarray(sessions),
        channel_names=preprocessing.CHANNEL_NAMES,
        sample_rate_hz=np.asarray(preprocessing.SAMPLE_RATE_HZ),
        window_size=np.asarray(preprocessing.WINDOW_SIZE),
        accel_range_g=np.asarray(preprocessing.ACCEL_RANGE_G, dtype=np.float32),
        gyro_range_dps=np.asarray(preprocessing.GYRO_RANGE_DPS, dtype=np.float32),
        normalization=np.asarray("accel/(8*9.80665), gyro/radians(500)"),
    )
    print(f"test: X={x.shape}, counts={counts.tolist()}, "
          f"range=[{x.min():.4f}, {x.max():.4f}] -> {output_path}")


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", type=Path, nargs="+", required=True,
                        help="one or more session directories directly containing CSVs")
    parser.add_argument("--output", type=Path,
                        help="destination .npz file (default: processed/"
                             "<directory_names_joined_by__>_test.npz beside this script)")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    convert(args.input, args.output)
