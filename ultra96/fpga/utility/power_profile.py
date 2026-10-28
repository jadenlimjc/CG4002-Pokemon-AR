"""Inspect, apply, and restore temporary Ultra96 power settings.

Run ``status`` as a normal user. Run ``apply`` and ``restore`` with sudo while
preserving the PYNQ environment, for example ``sudo -E python3 power_profile.py``.
No setting is made persistent across reboot.
"""

import argparse
import json
import os
import subprocess
from pathlib import Path


CPU_ROOT = Path("/sys/devices/system/cpu")
POLICY = CPU_ROOT / "cpufreq" / "policy0"
DEFAULT_STATE = Path(__file__).with_name("power_profile_state.json")


def read(path):
    path = Path(path)
    return path.read_text().strip() if path.exists() else None


def write(path, value):
    Path(path).write_text(str(value))


def cpu_directories():
    return sorted(
        (path for path in CPU_ROOT.glob("cpu[0-9]*") if path.name[3:].isdigit()),
        key=lambda path: int(path.name[3:]),
    )


def service_active(name):
    result = subprocess.run(
        ["systemctl", "is-active", "--quiet", name], check=False
    )
    return result.returncode == 0


def pl_clock_mhz():
    try:
        from pynq import Clocks
        return float(Clocks.fclk0_mhz)
    except Exception:
        return None


def snapshot(services=()):
    # Save every setting that apply() may change so restore() is reversible.
    cores = {}
    for cpu in cpu_directories():
        online_file = cpu / "online"
        cores[cpu.name] = read(online_file) if online_file.exists() else "1"
    return {
        "cpu": {
            "governor": read(POLICY / "scaling_governor"),
            "min_khz": read(POLICY / "scaling_min_freq"),
            "max_khz": read(POLICY / "scaling_max_freq"),
            "current_khz": read(POLICY / "scaling_cur_freq"),
            "available_governors": read(POLICY / "scaling_available_governors"),
            "available_frequencies": read(POLICY / "scaling_available_frequencies"),
        },
        "cores": cores,
        "pl_fclk0_mhz": pl_clock_mhz(),
        "services": {name: service_active(name) for name in services},
    }


def print_status(services=()):
    print(json.dumps(snapshot(services), indent=2))


def require_root():
    if os.geteuid() != 0:
        raise PermissionError("Apply/restore requires root; use sudo -E python3")


def set_pl_clock(mhz):
    # FCLK0 controls the programmable-logic accelerator clock.
    from pynq import Clocks
    Clocks.fclk0_mhz = float(mhz)
    actual = float(Clocks.fclk0_mhz)
    print(f"FCLK0 requested={mhz:g} MHz actual={actual:g} MHz")


def apply(args):
    require_root()
    if args.online_cores < 1:
        raise ValueError("At least CPU0 must remain online")
    if args.state.exists() and not args.overwrite_state:
        raise FileExistsError(
            f"{args.state} already exists; restore it first or use --overwrite-state"
        )

    # Snapshot first; the profile is temporary and recoverable.
    state = snapshot(args.stop_service)
    args.state.write_text(json.dumps(state, indent=2) + "\n")
    print(f"Saved original state to {args.state}")

    cores = cpu_directories()
    if args.online_cores > len(cores):
        raise ValueError(f"Board exposes only {len(cores)} CPU cores")
    # Keep CPU0 online; disable only the unused secondary cores.
    for cpu in cores[1:]:
        write(cpu / "online", 1 if int(cpu.name[3:]) < args.online_cores else 0)

    if args.cpu_khz is not None:
        available = read(POLICY / "scaling_available_frequencies")
        if available and str(args.cpu_khz) not in available.split():
            raise ValueError(
                f"Unsupported CPU frequency {args.cpu_khz}; available: {available}"
            )
        governors = (read(POLICY / "scaling_available_governors") or "").split()
        if "userspace" not in governors:
            raise RuntimeError(f"userspace governor unavailable: {' '.join(governors)}")
        # Userspace governor allows an explicit CPU clock selection.
        write(POLICY / "scaling_governor", "userspace")
        write(POLICY / "scaling_setspeed", args.cpu_khz)

    # Lowering FCLK0 trades FPGA throughput for dynamic power.
    if args.pl_mhz is not None:
        set_pl_clock(args.pl_mhz)

    for name in args.stop_service:
        if state["services"][name]:
            subprocess.run(["systemctl", "stop", name], check=True)

    print("Applied temporary profile:")
    print_status(args.stop_service)


def restore(args):
    require_root()
    # Restore cores, CPU policy, PL clock, and stopped services.
    state = json.loads(args.state.read_text())

    # Bring cores back before restoring the shared CPU-frequency policy.
    for cpu_name, online in state["cores"].items():
        online_file = CPU_ROOT / cpu_name / "online"
        if online_file.exists():
            write(online_file, online)

    cpu = state["cpu"]
    if cpu.get("min_khz") is not None:
        write(POLICY / "scaling_min_freq", cpu["min_khz"])
    if cpu.get("max_khz") is not None:
        write(POLICY / "scaling_max_freq", cpu["max_khz"])
    if cpu.get("governor") is not None:
        write(POLICY / "scaling_governor", cpu["governor"])
    # A userspace governor does not automatically return to the frequency that
    # was active before the profile was applied. Restore its saved setpoint
    # explicitly after restoring the governor.
    if (
        cpu.get("governor") == "userspace"
        and cpu.get("current_khz") is not None
    ):
        write(POLICY / "scaling_setspeed", cpu["current_khz"])

    if state.get("pl_fclk0_mhz") is not None:
        set_pl_clock(state["pl_fclk0_mhz"])

    for name, was_active in state.get("services", {}).items():
        if was_active:
            subprocess.run(["systemctl", "start", name], check=True)

    args.state.unlink()
    print("Restored original state and removed the state file.")


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    commands = parser.add_subparsers(dest="command", required=True)

    status = commands.add_parser("status", help="show current controllable state")
    status.add_argument("--service", action="append", default=[])

    configure = commands.add_parser("apply", help="save state and apply a profile")
    configure.add_argument("--cpu-khz", type=int)
    configure.add_argument("--online-cores", type=int, default=4)
    configure.add_argument("--pl-mhz", type=float)
    configure.add_argument("--stop-service", action="append", default=[])
    configure.add_argument("--overwrite-state", action="store_true")

    commands.add_parser("restore", help="restore the saved state")
    return parser.parse_args()


def main():
    args = parse_args()
    if args.command == "status":
        print_status(args.service)
    elif args.command == "apply":
        apply(args)
    else:
        restore(args)


if __name__ == "__main__":
    main()
