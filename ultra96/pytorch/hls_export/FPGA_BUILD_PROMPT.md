# Build and verify the Ultra96 FPGA model

Use the following prompt to run the complete local build from a trained
checkpoint through a packaged FPGA overlay.

---

Carry out the complete FPGA build and verification workflow in this repository.
Execute the tools, monitor them until completion, resolve build issues within
scope, and report the actual results. Start from an existing trained checkpoint.

## Inputs

- **Checkpoint:** use the path I provide. If I provide none, select the newest
  completed matching temporal-model run under
  `ultra96/pytorch/saved_checkpoints`, using run timestamps and checkpoint JSON.
  Pin that exact checkpoint for every subsequent step. Exclude LOSO fold models
  unless I explicitly select one.
- **Dataset:** `ultra96/real_data/processed_50hz_128/real_gestures_test.npz`,
  unless I provide a different matching dataset.
- **Target:** Ultra96 V2, `xczu3eg-sbva484-1-i`, 100 MHz / 10 ns.
- **Tools:** the existing Python environment and installed Vitis/Vivado 2025.1.
  Check actual installation paths before starting.

The expected temporal architecture has six input channels, kernels `(7, 5, 7)`,
dilations `(1, 2, 4)`, four temporal pooling bins, and a `512 -> 64 -> 11`
classifier. Validate the checkpoint against the current exporter, HLS header,
dataset metadata and class order. Architecture is independent of dataset;
hardware compatibility also depends on input shape and class count/order.

## Working rules

- Read applicable repository instructions and the current build scripts first.
- Run from the repository root and preserve unrelated working-tree changes.
- Continue through the authorized local workflow without asking for routine
  confirmations. Respect tool approval requirements when they apply.
- Keep me informed during long runs. Save logs under the appropriate ignored
  `build/` directory and monitor both exit status and tool reports.
- Use the existing Tcl scripts and source files. Make focused fixes if a real
  build issue requires them, then repeat the affected verification stages.
- Preserve existing deployment files before replacing them. Archive existing
  generated projects before a fresh build; retain their reports and outputs.
  Moving a generated project may invalidate absolute paths inside it, so treat
  the archive as build history rather than assuming it remains directly usable.
- Leave training, Git staging/commits, physical-board programming and network
  uploads outside this task unless I separately request them.

## 1. Preflight and export

Inspect these files and use their current options:

- `ultra96/pytorch/hls_export/export_weights.py`
- `ultra96/pytorch/hls_export/verify_csim.py`
- `ultra96/vitis/build_hls.tcl`
- `ultra96/vivado/build_vivado.tcl`
- `ultra96/fpga/deployment/cnn_pynq_ultra96.py`

Confirm that the checkpoint, sidecar JSON, dataset, dependencies and tools exist.
Check for active builds before moving any generated directory. Record the
selected checkpoint and its SHA-256.

Export the weights, BN coefficients, golden vectors and model manifest using
the selected checkpoint explicitly. Example PowerShell commands:

```powershell
$python = ".\ultra96\.venv\Scripts\python.exe"
$checkpoint = "<resolved checkpoint path>"
$data = "ultra96/real_data/processed_50hz_128/real_gestures_test.npz"

& $python -m ultra96.pytorch.hls_export.export_weights --checkpoint $checkpoint --test-data $data
if ($LASTEXITCODE -ne 0) { throw "Weight export failed" }
```

Confirm the generated `ultra96/vitis/weights.h`, `golden_input.dat`,
`golden_output.dat` and `model_manifest.json` correspond to the selected model.
If the dataset or checkpoint is incompatible with the hardware, explain the
specific mismatch before attempting architectural changes.

## 2. Run Vitis HLS

Run C simulation, HLS synthesis and IP export:

```powershell
$env:GESTURE_HLS_PART = "xczu3eg-sbva484-1-i"
$env:GESTURE_HLS_STAGE = "export"
& "C:\Xilinx\2025.1\Vitis\bin\vitis-run.bat" --mode hls --tcl ultra96/vitis/build_hls.tcl
if ($LASTEXITCODE -ne 0) { throw "HLS build/export failed" }
```

Wait for successful completion. Confirm fresh IP output under
`ultra96/vitis/build/gesture_cnn/solution1/impl/ip`, including `component.xml`.
Inspect synthesis timing/resource reports and any errors or critical warnings.

Run RTL co-simulation too:

```powershell
$env:GESTURE_HLS_STAGE = "cosim"
& "C:\Xilinx\2025.1\Vitis\bin\vitis-run.bat" --mode hls --tcl ultra96/vitis/build_hls.tcl
if ($LASTEXITCODE -ne 0) { throw "RTL co-simulation failed" }
$env:GESTURE_HLS_STAGE = "export"
```

Require an explicit C/RTL co-simulation PASS. Investigate deadlocks, mismatched
logits, invalid AXI framing or meaningful unknown-value warnings. If source or
weights change after IP export, regenerate the IP before the Vivado build.

## 3. Compare against PyTorch

Use the compiled testbench and the same checkpoint/dataset to verify every test
window:

```powershell
& $python -m ultra96.pytorch.hls_export.verify_csim --checkpoint $checkpoint --data $data --all
if ($LASTEXITCODE -ne 0) { throw "PyTorch/C-simulation comparison failed" }
```

Inspect `ultra96/vitis/csim_validation.json`. Report sample count, maximum logit
error, prediction agreement, floating-point accuracy and fixed-point accuracy.
Check prediction agreement separately: the script reports differing classes but
does not automatically fail solely because predictions differ.

Account for Windows Vitis runtime DLL paths. If an optimized native simulator is
needed for speed, compile it from the current sources, generated weights and
actual Vitis headers. Preserve equivalent checks and record how the results
were produced. Keep the existing numeric tolerances unless there is a justified
change; do not relax them merely to obtain a pass.

## 4. Run Vivado

The script creates a fresh project at
`ultra96/vivado/build/temporal_overlay`. If that project already exists, archive
it with a unique timestamp before invoking the script. Preserve the previous
board bundle as well so a failed rebuild cannot be mistaken for a new success.

```powershell
& "C:\Xilinx\2025.1\Vivado\bin\vivado.bat" -mode batch -source ultra96/vivado/build_vivado.tcl
if ($LASTEXITCODE -ne 0) { throw "Vivado build failed" }
```

Monitor the individual IP synthesis runs, top-level synthesis, implementation
and bitstream generation. Require successful setup and hold timing after
routing, using the actual reports rather than HLS timing estimates.

Confirm these outputs were generated by this build:

- `ultra96/vivado/build/temporal_overlay/timing_summary.rpt`
- `ultra96/vivado/build/temporal_overlay/utilization.rpt`
- `ultra96/vivado/build/board_bundle/gesture_cnn.bit`
- `ultra96/vivado/build/board_bundle/gesture_cnn.hwh`

If I provide a different dataset, check the bundle's dataset too: the current
Vivado Tcl script copies the default real-data NPZ. Package the selected matching
dataset under the expected filename and record that choice.

## 5. Validate and publish the local deployment

Check that the bundle includes the matching bitstream/handoff pair, driver,
evaluator, data-source helper, golden vectors and test dataset. Check the HWH
for the expected CNN IP and confirm that the build configuration matches the
architecture and window size recorded in the export manifest.

Back up the existing `.bit`, `.hwh`, golden vectors and dataset in
`ultra96/fpga/deployment` to a uniquely named ignored build directory. Then copy
the validated replacement artifacts into that deployment directory. Confirm
the copied files' hashes match the bundle.

Keep exported model provenance with the bundle. Deployment JSON files are
optional runtime metadata; respect my preference if I have removed them from
`fpga/deployment`. Store HLS results under `vitis` and Vivado results under
`vivado`, using portable paths where practical. Record checkpoint/source hashes,
verification results, routed timing, utilization and final artifact hashes.

Check that the packaged evaluator imports and its `--help` works without PYNQ
hardware access. Validate the packaged dataset's dimensions, sampling rate,
class order and sample count against the selected inputs.

## Completion report

Report only measured or verified results:

- Selected checkpoint and dataset.
- C simulation, PyTorch comparison and RTL co-simulation results.
- Vivado synthesis/implementation status, routed setup/hold slack and utilization.
- Locations of the new `.bit`/`.hwh`, board bundle, reports and backups.
- Any source fixes, unresolved limitations or failed checks.

Explicitly distinguish simulation/build verification from physical-board
testing. Finish with the board commands to run after copying the bundle:

```bash
python3 cnn_pynq_ultra96.py
python3 evaluate_fpga.py --overlay gesture_cnn.bit --data real_gestures_test.npz
```
