# Temporal CNN on Ultra96

The hardware now implements the PyTorch `temporal` preset: Conv1d kernels
`(7, 5, 7)`, dilations `(1, 2, 4)`, same-length padding `(3, 4, 12)`,
two MaxPool2 stages, four adaptive average-pooling bins, and a `512 -> 64 -> 11`
classifier. Pooling flattens in channel/bin order, matching PyTorch.
Inputs remain sensor-range-normalized `[6, 128]` windows at 50 Hz.
DMA sends 768 IEEE-754 floats in time/channel order and receives 11 float logits.
Preprocessing and the eleven-class label order are unchanged.

## Export and validate

Run from the repository root in PowerShell, using the existing AI environment:

```powershell
$checkpoint = "ultra96/pytorch/saved_checkpoints/50hz_128/2026-11-09_00-23-31_578104/gesture_1dcnn_real_50hz_128_best.pth"
.\ultra96\.venv\Scripts\python.exe -m ultra96.pytorch.hls_export.export_weights --checkpoint $checkpoint
```

The exporter checks the synthesis header against the checkpoint, computes BN
coefficients using Vitis fixed-point arithmetic, and writes `weights.h`, golden
vectors and `model_manifest.json` in `ultra96/vitis`. The manifest identifies the
source checkpoint and records its SHA-256 and the generated weights' SHA-256.
Legacy checkpoints are rejected by the temporal exporter.

Build with Vitis 2025.1 (adjust its installation path if needed):

```powershell
& "C:\Xilinx\2025.1\Vitis\bin\vitis-run.bat" --mode hls --tcl ultra96/vitis/build_hls.tcl
```

The script runs C simulation, HLS synthesis and IP export for
`xczu3eg-sbva484-1-i` at a 10 ns clock. Output is under
`ultra96/vitis/build/gesture_cnn/solution1/`; the exported Vivado IP is in
`impl/ip`. Set `$env:GESTURE_HLS_STAGE` to `csim`, `synth` or `cosim` to run a
different stage; the default is `export`. `cosim` runs RTL co-simulation after
synthesis. Override the target using `$env:GESTURE_HLS_PART` if your board differs.

The C++ testbench checks exact agreement between the streaming kernel and an
independent fixed-point reference, plus dilated padding, ordered/uneven pooling,
saturation, rounding and AXI framing. Compare against floating-point PyTorch on
the entire test set after C simulation has built its executable:

```powershell
.\ultra96\.venv\Scripts\python.exe -m ultra96.pytorch.hls_export.verify_csim --checkpoint $checkpoint --all
```

Without `--all`, validation selects one window per class. `--indices` selects
specific test windows. `vitis/csim_validation.json` records quantization error,
prediction agreement and both accuracies. Floating-point tolerance remains
`atol=0.50, rtol=0.10`; the independent fixed-point reference requires exact logits.
For a different host compiler, pass `--executable` to its compiled testbench.

## Rebuild the overlay

Vivado sources and build instructions are in
[`../vivado`](../vivado/README.md). Its block design uses CNN IP version 2.0.
Build a fresh Vivado project from the repository root:

```powershell
& "C:\Xilinx\2025.1\Vivado\bin\vivado.bat" -mode batch -source ultra96/vivado/build_vivado.tcl
```

This creates `vivado/build/temporal_overlay`, generates the wrapper and IP products, runs
synthesis and implementation, checks setup/hold timing, and generates a matching
bitstream and handoff. It stages a self-contained board directory in
`vivado/build/board_bundle`, including the new `.bit`/`.hwh`, Python scripts,
golden vectors, export manifest and test dataset. The original neighbouring
Vivado project is untouched. For another fresh build, move the generated
`vivado/build/temporal_overlay` directory aside first; the script will not overwrite it.

To upgrade your existing Vivado project manually instead:

1. Add `vitis/build/gesture_cnn/solution1/impl/ip` to the IP repository paths.
2. Refresh the IP catalog and upgrade the gesture CNN cell to exported IP version
   **2.0**. Retain its AXI streams, AXI-Lite control, DMA, clock and reset connections.
3. Validate the block design, regenerate output products, run synthesis and
   implementation, and generate the bitstream. Check final timing and utilization;
   HLS estimates alone do not establish that placement and routing succeeds.
4. Copy the new `.bit` and corresponding block-design `.hwh` to the board with
   the same basename, for example `gesture_cnn.bit` and `gesture_cnn.hwh`.

The kernel exposes a read-only `model_id` output at AXI-Lite offset `0x10`,
valid after inference completes. For 128 samples and 11 classes the value is
`0x5400800b`. The driver checks it before returning logits and rejects old or
different-window overlays. This identifies the architecture/window, not the
individual trained weights; keep the export manifest with the build artifacts.

## Board files and evaluation

Copy these files into a single board directory:

- The rebuilt `gesture_cnn.bit` / `gesture_cnn.hwh` pair.
- `deployment/cnn_pynq_ultra96.py`, `utility/evaluate_fpga.py` and
  `utility/evaluation_data.py` from this directory.
- `vitis/golden_input.dat`, `vitis/golden_output.dat` and
  `vitis/model_manifest.json` from the export.
- The matching `real_data/processed_50hz_128/real_gestures_test.npz`.

From that directory on the board:

```bash
python3 cnn_pynq_ultra96.py
python3 evaluate_fpga.py --overlay gesture_cnn.bit --data real_gestures_test.npz
```

The first command verifies the golden vector. The second measures accuracy,
latency and throughput; its JSON includes the verified hardware model identity.
The DMA and accelerator still use the existing bounded waits and fault recovery.
