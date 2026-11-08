# Vivado overlay build

This directory contains the Ultra96 block design and Vivado build script.
Vitis HLS sources and exported CNN IP are in `../vitis`; board drivers and
evaluation tools are in `../fpga`.

- `design/design_1/design_1.bd`: processing system, DMA, AXI interconnect,
  clock/reset connections and temporal CNN IP version 2.0. Adapted from the
  original neighbouring `pokemon_vivado` project.
- `build_vivado.tcl`: creates a fresh project, generates IP products and the
  wrapper, runs synthesis and implementation, and checks setup/hold timing.
- `build/temporal_overlay/`: generated project, bitstream, handoff and reports.
- `build/board_bundle/`: packaged bitstream, handoff, Python tools, golden
  vectors, model manifest and matching test dataset.

First export the trained weights and build the HLS IP, following
[the FPGA guide](../fpga/README.md#export-and-validate). Then run from the
repository root:

```powershell
& "C:\Xilinx\2025.1\Vivado\bin\vivado.bat" -mode batch -source ultra96/vivado/build_vivado.tcl
```

The target is `xczu3eg-sbva484-1-i`. The script reads the HLS IP from
`../vitis/build/gesture_cnn/solution1/impl/ip`. After implementation passes timing,
it stages the board bundle using drivers from `../fpga` and the processed
50 Hz / 128-sample test dataset from `../real_data`.

Generated outputs are ignored by Git. Move `build/temporal_overlay` aside before
another fresh build; the script refuses to overwrite an existing project.
The earlier completed build and its bundle remain under `../vitis/build/vivado`
and `../vitis/build/board_bundle`; their recorded paths describe that build.

For board commands and manual IP upgrades, see
[the FPGA deployment guide](../fpga/README.md).
