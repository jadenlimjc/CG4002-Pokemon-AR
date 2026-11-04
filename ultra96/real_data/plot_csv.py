"""Save one recording or every CSV in a folder as PNGs using its original sensor values.

Examples (from the repository root):
    python ultra96/real_data/plot_csv.py benjamin/benjamin_recordings_8_Oct/stopaim9.csv
    python ultra96/real_data/plot_csv.py benjamin/benjamin_recordings_8_Oct -o plots
    python ultra96/real_data/plot_csv.py benjamin --match stopaim -o plots

Folder inputs include subfolders; output folders preserve their structure.
Raw readings use the original 100 Hz time axis. Window markers match
preprocessing's --sample-rate and --window-size (defaults: 50 Hz / 128).
"""

import argparse
import csv
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

if __package__:
    from .preprocess_for_training import (
        load_csv, motion_centre, load_centre_overrides, FILENAME_PATTERN,
        WINDOW_SIZE, SAMPLE_RATE_HZ, DEFAULT_SAMPLE_RATE_HZ, resample_signal, target_sample_rate,
    )
else:
    from preprocess_for_training import (
        load_csv, motion_centre, load_centre_overrides, FILENAME_PATTERN,
        WINDOW_SIZE, SAMPLE_RATE_HZ, DEFAULT_SAMPLE_RATE_HZ, resample_signal, target_sample_rate,
    )


def preprocessing_window(source, centre_seconds=None,
                         sample_rate=DEFAULT_SAMPLE_RATE_HZ, window_size=WINDOW_SIZE):
    if type(sample_rate) is not int or not 0 < sample_rate <= SAMPLE_RATE_HZ or window_size < 4:
        raise ValueError("sample_rate must be an integer from 1 to 100 and window_size must be at least 4")
    signal = load_csv(source)
    match = FILENAME_PATTERN.fullmatch(source.name)
    neutral = match is not None and match.group("prefix").lower() == "neutral"
    automatic = len(signal) // 2 if neutral else motion_centre(signal)
    if centre_seconds is None:
        centre = automatic
    else:
        if not 0 <= centre_seconds <= (len(signal) - 1) / SAMPLE_RATE_HZ:
            raise ValueError("Override centre is outside the recording")
        centre = round(centre_seconds * SAMPLE_RATE_HZ)
    signal = resample_signal(signal, sample_rate)
    automatic = min(len(signal) - 1, round(automatic * sample_rate / SAMPLE_RATE_HZ))
    centre = min(len(signal) - 1, round(centre * sample_rate / SAMPLE_RATE_HZ))
    start = centre - window_size // 2
    end = start + window_size
    padding = max(0, -start) + max(0, end - len(signal))
    return automatic, centre, start, end, padding


def plot_csv(source, output, centre_seconds=None,
             sample_rate=DEFAULT_SAMPLE_RATE_HZ, window_size=WINDOW_SIZE):
    channels = ("ax", "ay", "az", "gx", "gy", "gz")
    try:
        with source.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            missing = set(channels) - set(reader.fieldnames or [])
            if missing:
                raise ValueError(f"Missing CSV columns: {', '.join(sorted(missing))}")
            rows = [{key: float(row[key]) for key in channels}
                    for row in reader]
    except (OSError, ValueError, TypeError) as error:
        raise ValueError(f"Cannot read {source}: {error}") from error
    if not rows:
        raise ValueError("CSV contains no samples")

    automatic, centre, start, end, padding = preprocessing_window(source, centre_seconds, sample_rate, window_size)
    # Preserve raw CSV values on the source time axis; markers use output-rate indices.
    time = [i / SAMPLE_RATE_HZ for i in range(len(rows))]
    centre_kind = "automatic" if centre_seconds is None else "manual override"
    fig, axes = plt.subplots(2, 1, figsize=(12, 6), sharex=True)
    for ax, names, label in zip(axes, (channels[:3], channels[3:]),
                               ("Acceleration (raw CSV units)", "Gyroscope (raw CSV units)")):
        for name in names:
            ax.plot(time, [row[name] for row in rows], label=name, linewidth=1)
        ax.axvspan(start / sample_rate, end / sample_rate,
                   color="orange", alpha=0.2,
                   label=f"Selected {window_size}-sample window ({window_size / sample_rate:.2f} s)")
        ax.axvline(centre / sample_rate, color="black", linestyle="--",
                   label=f"Centre ({centre_kind})")
        if centre_seconds is not None:
            ax.axvline(automatic / sample_rate, color="gray", linestyle=":",
                       label="Automatic centre")
        ax.set_ylabel(label)
        ax.legend(loc="upper right")
        ax.grid(alpha=0.25)
    axes[-1].set_xlabel("Seconds from recording start (raw CSV at 100 Hz)")
    fig.suptitle(f"{source.name} | {len(rows)} source samples at 100 Hz\n"
                 f"{sample_rate} Hz | {window_size}-sample window ({window_size / sample_rate:.2f} s) | "
                 f"Centre: {centre / sample_rate:.2f} s ({centre_kind}) | Edge padding: {padding} output samples")
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
    parser.add_argument("--centre-overrides", type=Path,
                        help="Same filename,centre_seconds CSV used by preprocessing")
    parser.add_argument("--data-root", type=Path, default=Path(__file__).resolve().parent,
                        help="Root for override filenames; match preprocessing --input (default: real_data)")
    parser.add_argument("-o", "--output", type=Path,
                        help="Output PNG for a file, or output folder for a folder (default: beside each CSV)")
    parser.add_argument("--sample-rate", type=target_sample_rate, default=DEFAULT_SAMPLE_RATE_HZ,
                        help="preprocessing output rate, 1-99 Hz; default: 50 Hz")
    parser.add_argument("--window-size", type=int, default=WINDOW_SIZE,
                        help="samples per window, at least 4 (default: 128)")
    args = parser.parse_args()
    if args.window_size < 4:
        parser.error("--window-size must be at least 4")
    try:
        overrides = load_centre_overrides(args.centre_overrides)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    source = args.source
    if not source.exists():
        source = Path(__file__).resolve().parent / source
    if not source.exists():
        parser.error(f"Path does not exist: {args.source}")

    if source.is_dir():
        files = sorted(path for path in source.rglob("*")
                       if path.is_file() and path.suffix.lower() == ".csv"
                       and "rename_logs" not in path.relative_to(source).parts
                       and (args.centre_overrides is None
                            or path.resolve() != args.centre_overrides.resolve()))
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
            try:
                filename = path.resolve().relative_to(args.data_root.resolve()).as_posix()
            except ValueError:
                if args.centre_overrides is not None:
                    raise ValueError(f"{path} is outside --data-root") from None
                filename = None
            plot_csv(path, output, overrides.get(filename), args.sample_rate, args.window_size)
        except (OSError, ValueError) as error:
            print(f"Skipped {path}: {error}", file=sys.stderr)
            failed += 1
    print(f"Generated {len(files) - failed} plot(s); {failed} failed.")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
