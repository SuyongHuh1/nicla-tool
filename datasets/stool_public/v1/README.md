# Stool FOMO reproducibility dataset v1

This directory is the minimal reviewed dataset needed to reproduce the
stool-only Tiny FOMO training and independent evaluation. Intermediate AI
outputs, previews, review backups, and duplicate checking-session copies are
not included.

## Contents

```text
train/
  metadata.jsonl
  images/       195 source frames
  masks/        195 human-reviewed segmentation masks
  labels/       195 final YOLO-format boxes
evaluation/inference_e01/
  metadata.jsonl
  images/       15 untouched independent frames
  masks/        15 human-reviewed masks
  labels/       15 final boxes
dataset_summary.json
checksums.sha256
DATA_CARD.md
```

The evaluation images are kept out of training and augmentation. Six physical
stool groups (`S01` through `S06`) are used for grouped cross-validation. A
single empty baseline frame is retained in the training session with zero
instances.

## Reproduce the final model

From the repository root on Windows PowerShell:

```powershell
.\setup_windows.ps1
.\.venv\Scripts\python.exe -m pip install -r laptop\requirements-training.txt
.\reproduce_stool_v1.ps1
```

The command verifies every published dataset checksum, builds a leakage-safe
manifest, trains the 96x96 Tiny CNN-FOMO model for 30 epochs with the selected
`default` augmentation, chooses a threshold on `S05`, evaluates once on `S06`,
and evaluates the 15 independent frames without modifying them.

To rerun all three augmentation presets over all six leave-one-stool-out folds:

```powershell
.\reproduce_stool_v1.ps1 -RunCrossValidation
```

This trains 18 cross-validation models before training the final fixed-split
model, so it takes longer than the default command.

Outputs are written to a new timestamped folder under `training_runs/`, which
is intentionally ignored by Git.

## Expected reference result

The exact floating-point training trace may vary slightly by TensorFlow and CPU
build. The committed v1 reference run produced:

- six-fold mean F1: 93.29% with `default` augmentation
- fixed S06 test F1: 94.29%
- independent set: TP 19, FP 5, FN 0, F1 88.37%
- int8 TFLite model size: 18,672 bytes

A clean-worktree verification using only this public directory completed the
entire pipeline and produced TP 19, FP 4, FN 0 (F1 90.48%). Native Windows
TensorFlow/oneDNN can produce small run-to-run training differences even with
the fixed seed. The versioned reference artifact and both metric sets are
recorded in `reports/stool_fomo_v1_reference.json`.

See `DATA_CARD.md` for collection conditions, annotation policy, limitations,
and intended use.
