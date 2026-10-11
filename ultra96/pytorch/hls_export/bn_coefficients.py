"""Generate fixed-point BN constants using Vitis headers and a host C++ compiler.

Also upgrades an existing weights.h without loading a checkpoint:
python bn_coefficients.py --weights-header ../../vitis/weights.h --hls-include-dir PATH
"""
import argparse
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile


def _version_key(path):
    return tuple(int(part) for part in re.findall(r"\d+", str(path)))


def _installation_roots():
    if sys.platform == "win32":
        drive = os.environ.get("SystemDrive", "C:")
        return [Path(drive + "/Xilinx"), Path(drive + "/AMD")]
    return [Path("/mnt/c/Xilinx"), Path("/mnt/c/AMD"), Path("/opt/Xilinx"), Path("/opt/AMD")]


def _find_hls_include(hls_include_dir=None):
    candidates = [Path(hls_include_dir)] if hls_include_dir else []
    if not hls_include_dir:
        for name in ("XILINX_HLS", "XILINX_VITIS"):
            if os.environ.get(name):
                candidates.append(Path(os.environ[name]) / "include")
        for root in _installation_roots():
            candidates.extend(sorted(root.glob("*/Vitis/include"), key=_version_key, reverse=True))
            candidates.extend(sorted(root.glob("Vitis_HLS/*/include"), key=_version_key, reverse=True))
    include = next((p for p in candidates
                    if (p / "ap_fixed.h").is_file() and (p / "hls_math.h").is_file()), None)
    if include is None:
        raise ValueError("Provide --hls-include-dir pointing to Vitis include/ "
                         "or set XILINX_HLS/XILINX_VITIS. Exact BN export requires HLS headers.")
    return include.resolve()


def _find_compiler(include, cxx=None):
    command = cxx or os.environ.get("CXX")
    if command:
        # A single executable path may contain spaces and Windows backslashes.
        path = command.strip('"')
        if Path(path).is_file():
            return [path]
        words = shlex.split(command, posix=sys.platform != "win32")
        return [word.strip('"') for word in words]
    # Prefer Vitis's bundled MinGW on Windows, matching the installed headers.
    if sys.platform == "win32":
        for base in (include.parent, include.parent.parent):
            matches = sorted(base.glob("tps/mingw/*/win64.o/nt/bin/g++.exe"),
                             key=_version_key, reverse=True)
            matches += list(base.glob("tps/win64/msys64/mingw64/bin/g++.exe"))
            if matches:
                return [str(matches[0])]
    for name in ("g++", "clang++"):
        if shutil.which(name):
            return [shutil.which(name)]
    raise ValueError("No host C++ compiler found. Provide --cxx with the path to "
                     "g++.exe (for example, Vitis's tps/mingw/.../bin/g++.exe).")


def generate_bn_coefficients(parameters, hls_include_dir=None, cxx=None):
    """parameters maps bnN_weight/bias/running_mean/running_var to flat values."""
    include = _find_hls_include(hls_include_dir)
    compiler = _find_compiler(include, cxx)
    rows = []
    for block, channels in ((1, 32), (2, 64), (3, 128)):
        arrays = [parameters[f"bn{block}_{suffix}"] for suffix in
                  ("weight", "bias", "running_mean", "running_var")]
        if any(len(values) != channels for values in arrays):
            raise ValueError(f"BN{block} requires {channels} values per parameter")
        rows.append(str(channels))
        # Match the original export's decimal literals before data_t conversion.
        rows.extend(" ".join(f"{float(v):.8f}" for v in values) for values in zip(*arrays))
    source = Path(__file__).resolve().parent / "precompute_bn.cpp"
    with tempfile.TemporaryDirectory(prefix="gesture_bn_") as tmp:
        executable = Path(tmp) / ("precompute_bn.exe" if sys.platform == "win32" else "precompute_bn")
        environment = os.environ.copy()
        # MinGW DLLs must be reachable both while compiling and running the helper.
        compiler_dir = Path(shutil.which(compiler[0]) or compiler[0]).resolve().parent
        environment["PATH"] = str(compiler_dir) + os.pathsep + environment.get("PATH", "")
        subprocess.run(compiler + ["-std=c++14", "-Wno-unknown-pragmas", "-I", str(include),
                                  str(source), "-o", str(executable)], check=True, env=environment)
        result = subprocess.run([str(executable)], input="\n".join(rows) + "\n",
                                text=True, capture_output=True, check=True, env=environment)
    return "// Precomputed with HLS fixed-point arithmetic; keep raw BN arrays for verification.\n" + result.stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--weights-header", type=Path, required=True)
    parser.add_argument("--hls-include-dir")
    parser.add_argument("--cxx", help="Host C++ compiler command (default: CXX or g++)")
    args = parser.parse_args()
    original = args.weights_header.read_bytes()
    text = original.decode()
    parameters = {}
    for name, body in re.findall(r"const data_t (bn\d+_\w+)\[\d+\]\s*=\s*\{(.*?)\};", text, re.S):
        parameters[name] = [float(v) for v in body.split(",") if v.strip()]
    coefficients = generate_bn_coefficients(parameters, args.hls_include_dir, args.cxx)
    text = re.sub(r"// Precomputed with HLS fixed-point arithmetic;[^\n]*\r?\n", "", text)
    text = re.sub(r"const accum_t bn\d+_(?:scale|shift)\[\d+\]\s*=\s*\{.*?\};\s*", "", text, flags=re.S)
    marker = "#endif // WEIGHTS_H"
    if text.count(marker) != 1:
        raise ValueError("Expected one WEIGHTS_H closing guard")
    text = text.replace(marker, coefficients + marker)
    text = text.replace("\r\n", "\n")
    if b"\r\n" in original:
        text = text.replace("\n", "\r\n")
    args.weights_header.write_bytes(text.encode())


if __name__ == "__main__":
    main()
