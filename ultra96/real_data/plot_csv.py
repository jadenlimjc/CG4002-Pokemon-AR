"""Save one recording or every CSV in a folder as PNGs using its original sensor values.

Examples (from the repository root):
    python ultra96/real_data/plot_csv.py benjamin/benjamin_recordings_8_Oct/stopaim9.csv
    python ultra96/real_data/plot_csv.py benjamin/benjamin_recordings_8_Oct -o plots
    python ultra96/real_data/plot_csv.py benjamin --match stopaim -o plots

Folder inputs include subfolders; output folders preserve their structure.
"""

import argparse
import csv
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


def plot_csv(source, output):
    channels = ("ax", "ay", "az", "gx", "gy", "gz")
    try:
        with source.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            missing = set(("timestamp_ms",) + channels) - set(reader.fieldnames or [])
            if missing:
                raise ValueError(f"Missing CSV columns: {', '.join(sorted(missing))}")
            rows = [{key: float(row[key]) for key in ("timestamp_ms",) + channels}
                    for row in reader]
    except (OSError, ValueError, TypeError) as error:
        raise ValueError(f"Cannot read {source}: {error}") from error
    if not rows:
        raise ValueError("CSV contains no samples")

    time = [(row["timestamp_ms"] - rows[0]["timestamp_ms"]) / 1000 for row in rows]
    fig, axes = plt.subplots(2, 1, figsize=(12, 6), sharex=True)
    for ax, names, label in zip(axes, (channels[:3], channels[3:]),
                               ("Acceleration (raw CSV units)", "Gyroscope (raw CSV units)")):
        for name in names:
            ax.plot(time, [row[name] for row in rows], label=name, linewidth=1)
        ax.set_ylabel(label)
        ax.legend(loc="upper right")
        ax.grid(alpha=0.25)
    axes[-1].set_xlabel("Seconds from recording start")
    fig.suptitle(f"{source.name} | {len(rows)} samples")
    fig.tight_layout()
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, format="png", dpi=150)
    plt.close(fig)
    print(f"Saved {output.resolve()}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="CSV or folder path, also relative to real_data")
    parser.add_argument("--match", default="",
                        help="Only plot CSV filenames containing this text (case-insensitive)")
    parser.add_argument("-o", "--output", type=Path,
                        help="Output PNG for a file, or output folder for a folder (default: beside each CSV)")
    args = parser.parse_args()
    source = args.source
    if not source.exists():
        source = Path(__file__).resolve().parent / source
    if not source.exists():
        parser.error(f"Path does not exist: {args.source}")

    if source.is_dir():
        files = sorted(path for path in source.rglob("*")
                       if path.is_file() and path.suffix.lower() == ".csv")
        if not files:
            parser.error(f"No CSV files found in {source}")
    else:
        files = [source]

    if args.match:
        files = [path for path in files if args.match.casefold() in path.stem.casefold()]
        if not files:
            parser.error(f"No CSV filenames containing {args.match!r} found in {source}")

    failed = 0
    for path in files:
        if args.output is None:
            output = path.with_suffix(".png")
        elif source.is_dir():
            output = args.output / path.relative_to(source).with_suffix(".png")
        else:
            output = args.output
        try:
            plot_csv(path, output)
        except (OSError, ValueError) as error:
            print(f"Skipped {path}: {error}", file=sys.stderr)
            failed += 1
    print(f"Generated {len(files) - failed} plot(s); {failed} failed.")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
