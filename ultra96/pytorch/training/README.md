# Single-head state-masked evaluation

The CNN retains one output layer for the original 11 labels. Training and
validation checkpoint selection are unchanged. Software test evaluation, LOSO,
and error inspection automatically restrict predictions by expected game state:

| State | Available labels |
| --- | --- |
| Normal | Neutral, Aim, Punch, Swipe, Guard, Flee, Switch Pokemon, Use Item, Uppercut |
| Aiming | Neutral, Stop Aim, Throw |

Masking excludes invalid logits before argmax/softmax; it does not add learned
heads or require new training data. For offline clips, the true gesture label
supplies expected state, and Neutral is evaluated in both states. These scores
assume correct game state, not measured live state tracking. Duplicated Neutral
means there are more supervised evaluation tasks than source windows.

State-conditioned scores are the main output. Unrestricted single-head scores
are preserved under `unrestricted` in JSON. Per-state scores are under `states`.
The confusion-matrix image has normal/aiming panels, with a JSON report beside
it. `train_baseline --evaluate` stores the test results in the existing `run.json`.
LOSO summary CSV adds normal, aiming and unrestricted balanced-accuracy columns.
Other datasets retain unrestricted evaluation. FPGA and communications are unchanged.

Refresh a completed single-head LOSO run without retraining:

```powershell
.\ultra96\.venv\Scripts\python.exe -m ultra96.pytorch.training.cross_validate_loso --reevaluate-run ultra96/pytorch/loso_runs/2026-11-09_00-35-48_013762
```

This refreshes saved predictions, plots, metrics, summary JSON/CSV and evaluation
metadata. Checkpoints and training results are retained. Archived dual-head
checkpoints are rejected; automatic software checkpoint selection skips them.

# Temporal CNN training

Training defaults to the `temporal` architecture for either dataset. Select
`--architecture temporal` or `--architecture legacy` independently of `--dataset`.
The temporal preset uses kernel sizes `(7, 5, 7)`,
dilations `(1, 2, 4)`, and four ordered average-pooling bins. Each final
convolutional feature covers up to 122 input samples (2.44 seconds at 50 Hz),
compared with 26 samples (0.52 seconds) in the original CNN. The classifier
receives 512 features, retaining coarse early/late position information.
This is a hypothesis to validate, not a guarantee of higher accuracy.

From the repository root, train a fresh checkpoint using the existing AI environment:

```powershell
.\ultra96\.venv\Scripts\python.exe -m ultra96.pytorch.training.train_baseline --architecture temporal --epochs 30 --augmentation imu
```

Repeat with `--architecture legacy` for a controlled comparison using the same
data, augmentation, and training settings. Compare validation results before
evaluating the selected model on a fresh holdout. Add `--evaluate` only when
ready to evaluate the best saved epoch on the test split.

The training pipeline saves all architecture options in checkpoint JSON.
Evaluation and error inspection reconstruct either architecture from that JSON.
Existing checkpoints remain loadable: the `Gesture1DCNN` constructor retains
legacy defaults when metadata lacks the new options. Existing Optuna and nested
regularization architecture searches retain their legacy search space; they do
not search the temporal preset.

The temporal FPGA/HLS implementation and exporter now match this architecture.
Re-export the trained weights and rebuild the HLS IP and Vivado bitstream before
deploying it. See [FPGA export, verification and deployment](../../fpga/README.md).

# Unseen-player evaluation

LOSO now defaults to the temporal architecture too. Pass `--architecture legacy`
to reproduce the original architecture; historical runs used legacy. Architecture
selection is recorded in `protocol.json` for new runs.

From the repository root, using the Python environment with the AI dependencies:

```bash
python -m ultra96.pytorch.training.cross_validate_loso --epochs 30
```

On Windows, the existing environment can be invoked directly:

```powershell
.\ultra96\.venv\Scripts\python.exe -m ultra96.pytorch.training.cross_validate_loso --epochs 30
```

To compare the current Optuna-tuned training settings using the same protocol:

```bash
python -m ultra96.pytorch.training.cross_validate_loso --epochs 30 --training-settings tuned
```

This uses `REAL_TRAINING_PARAMS` from `train_baseline.py` and records the actual
values in `protocol.json`. The default remains `--training-settings baseline`.
The tuned comparison is a development experiment: those hyperparameters were
previously selected using data from all four subjects, including the people
held out here. It is not an independent estimate of hyperparameter selection.

Add `--augment` to either LOSO or `train_baseline.py` to enable training-only
amplitude, noise, and speed augmentation:

```bash
python -m ultra96.pytorch.training.cross_validate_loso --epochs 30 --training-settings tuned --augment
```

For each training presentation, half the windows are left unchanged on average.
The others receive shared-axis speed scaling of 0.9–1.1 around the window centre
(linear interpolation, edge padding), amplitude scaling of 0.9–1.1 per sensor
group, and Gaussian noise with standard deviation 0.002 in normalized units.
Acceleration amplitude changes preserve the window's temporal mean to avoid
scaling its gravity offset. This is an approximation to motion variation, not
a physical simulation. Noise corresponds to about 0.157 m/s² or 1 degree/s.
All six channels share the same time mapping. The existing offline training
window offsets remain in use. Validation/test windows and saved NPZ arrays are
unchanged. A separate RNG seeded with 43 keeps augmentation reproducible without
changing the model's initialization or consuming its dropout/shuffle RNG.
The augmentation settings are saved in protocol, run, and checkpoint metadata;
augmentation is disabled by default and never used during inference.

An alternative IMU preset is available separately from the basic preset:

```bash
python -m ultra96.pytorch.training.cross_validate_loso --epochs 30 --training-settings tuned --augmentation imu
```

It perturbs half the training windows on average using a random proper 3D
rotation of up to 10 degrees shared by acceleration and gyro, a smooth monotonic
nonlinear time warp shared by all six channels, and smooth positive magnitude
envelopes in [0.9, 1.1] shared across the three axes of each sensor. Time warping
integrates a positive low-frequency speed curve and fixes the first and last
sample, without reordering or cutting the clip. This generates time variation;
it does not use dynamic time warping to align different recordings. Acceleration
magnitude modulation acts around its window mean as an approximate gravity
component, before rotating the whole vector. This keeps static gravity from
being amplified, but is not a full physical motion simulation. This preset has
no added sensor noise, axis permutations, or reflections. Use the same
`--augmentation imu` option with `train_baseline.py` if desired. Both presets
are opt-in; `--augment` remains an alias for the basic preset.

The default is 50 Hz, 128 samples, matching the current baseline. Use
`--sample-rate` and `--window-size` to evaluate another input configuration.
Use `--prepare-only` to build and audit the four folds without training.
`--input` must have `subject/session/recording.csv` folders. Root-level
`centre_overrides.csv` is used automatically, or pass `--centre-overrides`.

Each subject is held out once. All of that person's recordings become test
examples, with exactly one centred window per recording. For the other people,
trials 7–8 of each ten-trial block are validation recordings; the remaining
trials are training recordings. Offset augmentation is applied only after this
assignment, only to training recordings. Input normalization uses fixed sensor
ranges, with no statistics fitted to the held-out person. Missing training or
validation classes, subject leakage, and overlapping recordings fail the audit.

Every fold starts a new CNN and optimizer with seed 42. It trains for 30 epochs
by default and selects the checkpoint with highest validation balanced accuracy
(validation loss breaks ties). There is no early termination. The held-out
subject is evaluated only after checkpoint selection. The workflow uses fixed
baseline settings (Adam learning rate 0.001, weight decay 0.0001, dropout 0.3),
rather than Optuna settings previously selected using data from all subjects.
The existing architecture and preprocessing were developed on this dataset, so
these results remain a development estimate; a new person's live test provides
stronger independent evidence. Repeatedly changing settings based on LOSO test
scores also makes them development scores. Strict hyperparameter selection
requires an inner validation procedure that excludes each outer test subject.

Artifacts are saved under `ultra96/pytorch/loso_runs/<Singapore timestamp>/`:

- `protocol.json`: settings, subjects, split policy, and completion status.
- `<subject>/split_manifest.json`: subject lists and recording membership.
- `<subject>/training/`: best checkpoint, model metadata, and loss plot.
- `<subject>/metrics.json`, `predictions.csv`, `confusion_matrix.png`: test results.
- `summary.csv` and `summary.json`: per-person scores and equal-subject mean ±
  sample standard deviation, in percent. JSON also includes pooled metrics.

Balanced accuracy averages recall over classes present in that test subject.
Macro-F1 uses all 11 classes, assigning zero for undefined F1. Per-class support
is included so missing gestures are visible. Standard deviation describes the
variation among subjects; it is not a confidence interval. A partially completed
run has only completed folds in its summary: check `protocol.json` for completion.

These fold checkpoints live outside `saved_checkpoints` so automatic deployment
checkpoint selection cannot pick a model trained with one person excluded.
After settings are frozen, train a separate deployment model using all four
people. Do not choose a LOSO fold checkpoint because it scored best.

This evaluates classification of centred, labelled gesture clips. It does not
measure continuous live detection, false triggers, debounce, or FPGA accuracy.
Test those separately with a person who supplied no training recordings.

Every fold automatically audits subject separation, recording overlap, class
coverage, and the absence of augmentation in validation/test data before training.

## Nested regularization comparison

```bash
python -m ultra96.pytorch.training.regularize_loso --epochs 30
```

This compares the current settings, dropout 0.4, weight decay 0.001, and both
changes, with the learning rate and six-channel architecture fixed. Each outer
test person is excluded from all inner training and validation. Within the other
three subjects, train on two and validate on the third, rotating all three roles.
Every inner run starts fresh with seed 42. Candidates are compared by equal-subject
mean validation balanced accuracy, with validation loss breaking ties. A challenger
must gain at least 1 percentage point over current to be selected. This is a
practical cutoff, not a significance test. All 48 inner runs use up to 30 epochs;
they select the best validation checkpoint, without early termination.

The selected setting and a matched current-settings reference are each refitted
on all recordings from the three outer development subjects. Training duration is
the rounded median of that candidate's three inner best epochs, fixed before
looking at the outer test person. If current wins, the same refit serves both roles.
All test recordings have exactly one unaugmented centre window. Training uses
the existing offline offset windows, including for trial numbers previously
reserved for validation/test when those subjects are now exclusively training
subjects. The optional noise/rotation/speed augmentations are disabled.

This differs from the earlier LOSO runs, which reserved some recordings from each
training subject for same-person validation. Compare regularization against the
matched current-settings reference to isolate its effect. Do not attribute any
change from the earlier 78.29% score solely to stronger regularization.

Output is under `loso_runs/regularization/<timestamp>/`, including pool hashes,
subject/recording manifests, per-person `inner_results.json` and `selection.json`,
outer predictions and confusion matrices, `summary.json`, `current_reference/`,
`comparison.csv`, and `recommendation.json`. The summary reports the nested
selection procedure, which may select different settings for different outer
folds; it is not a test score for one fixed setting.

For final development training, pool the inner results to choose settings and
duration. Retain current if the selected outer procedure gains less than 1pp over
the matched reference. This final recommendation uses development results and
has no independent test score. Refit a deployment candidate on all four subjects
for the selected fixed duration, saving a compatible raw state dict plus JSON in
`deployment_candidate/`. It does not replace existing deployment weights, run
FPGA export, or register itself as the default software checkpoint. Architecture
and previous tuning already used these people, so this remains a single-seed
development comparison even though inner selection excludes each outer person.

