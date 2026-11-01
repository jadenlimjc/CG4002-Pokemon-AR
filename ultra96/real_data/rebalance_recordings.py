"""Fill missing validation/test trial numbers by moving training CSVs.

Preview by default; pass --apply to rename files. Work within each session,
gesture, and block of ten. Blocks with fewer than six recordings go entirely
into training; other blocks fill two validation and two test slots.
After applying, regenerate ALL NPZ splits and retrain from scratch.
"""

import argparse
import csv
from datetime import datetime
from pathlib import Path
import re


PATTERN = re.compile(r"^(neutral|aim|stopaim|throw|punch|swipe|guard|uturn|backpocket|frontpocket|uppercut)([1-9][0-9]*)\.csv$", re.I)
# Give each evaluation split one replacement before filling its second slot.
TARGET_ORDER = (9, 7, 10, 8)


def plan_moves(root):
    groups = {}
    for path in sorted(root.rglob("*.csv")):
        match = PATTERN.fullmatch(path.name)
        if not match:
            continue
        prefix, trial_text = match.groups()
        trial = int(trial_text)
        block = (trial - 1) // 10 * 10
        key = (path.parent, prefix.lower(), block)
        trials = groups.setdefault(key, {})
        if trial in trials:
            raise ValueError(f"Duplicate trial: {trials[trial]} and {path}")
        trials[trial] = path

    moves, warnings = [], []
    for (session, prefix, block), trials in sorted(groups.items()):
        if len(trials) < 6:
            # Four evaluation slots plus two training recordings cannot fit.
            # Move existing evaluation recordings into unused training slots,
            # so the unchanged preprocessing split rules put this whole block
            # in training. Existing training filenames stay intact.
            free_training = [block + n for n in range(1, 7)
                             if block + n not in trials]
            for trial in sorted(trials):
                if trial - block > 6:
                    destination = session / f"{prefix}{free_training.pop(0)}.csv"
                    moves.append((trials[trial], destination))
            continue
        training = [n for n in trials if n - block <= 6]
        donors = sorted(training, reverse=True)
        missing = [block + n for n in TARGET_ORDER if block + n not in trials]
        for target in missing:
            if not donors or len(training) <= 2:
                warnings.append(
                    f"{session.relative_to(root)}/{prefix}: cannot fill trial "
                    f"{target} while retaining two training recordings in block "
                    f"{block + 1}-{block + 10}"
                )
                continue
            donor = donors.pop(0)
            training.remove(donor)
            source = trials[donor]
            destination = session / f"{prefix}{target}.csv"
            moves.append((source, destination))
    return moves, warnings, len(groups)


def apply_moves(moves, log_path):
    # Check every path before making the first change.
    for source, destination in moves:
        if not source.is_file():
            raise FileNotFoundError(source)
        if destination.exists():
            raise FileExistsError(destination)
    # Exclusive creation prevents replacing an earlier audit log.
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("x", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["original_path", "new_path"])
        handle.flush()
        for source, destination in moves:
            if destination.exists():
                raise FileExistsError(destination)
            source.rename(destination)
            writer.writerow([str(source), str(destination)])
            handle.flush()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path(__file__).resolve().parent,
                        help="Data root, subject folder, or session (default: real_data)")
    parser.add_argument("--apply", action="store_true", help="Apply the previewed renames")
    args = parser.parse_args()
    root = args.input.resolve()
    if not root.is_dir():
        parser.error(f"Input directory does not exist: {root}")
    try:
        moves, warnings, group_count = plan_moves(root)
    except ValueError as error:
        parser.error(str(error))
    if not group_count:
        parser.error(f"No recognized recording CSVs found in {root}")
    for source, destination in moves:
        print(f"{source.relative_to(root)} -> {destination.relative_to(root)}")
    for warning in warnings:
        print(f"WARNING: {warning}")
    print(f"{len(moves)} renames; {len(warnings)} unfilled evaluation slots.")
    if not args.apply:
        print("Preview only. Run again with --apply to rename files.")
    elif moves:
        log_path = (Path(__file__).resolve().parent / "rename_logs"
                    / f"recording_renames_{datetime.now():%Y%m%d_%H%M%S_%f}.csv")
        apply_moves(moves, log_path)
        print(f"Applied. Rename log: {log_path}")
        print("Regenerate ALL NPZ splits, then retrain from scratch before evaluating.")
    else:
        print("No files changed.")


if __name__ == "__main__":
    main()
