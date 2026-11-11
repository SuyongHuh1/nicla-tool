# Stool FOMO v1 reproducibility report

- Date: 2026-11-11
- Repository: `SuyongHuh1/nicla-tool`
- Isolated branch: `codex/stool-fomo-repro-v1`
- Base commit: `af8ea65`

## Scope and isolation

This branch is prepared in a separate Git worktree. It contains only the
stool-model training, cross-validation, independent evaluation, curated public
dataset, versioned model, tests, and documentation needed for reproduction.

It does not change the shared Nicla runtime, vehicle code, wire protocol,
capture UI, or friend-review tools. The original working directory and its
uncommitted files were not reset, moved, or deleted.

## Published dataset

| Set | Images | Masks | Labels | Role |
|---|---:|---:|---:|---|
| `train` | 195 | 195 | 195 | grouped training/validation/test |
| `evaluation/inference_e01` | 15 | 15 | 15 | independent read-only evaluation |

- public directory size: 3.345 MB
- exact duplicate image hashes: 0
- training review states: 53 accepted, 142 corrected, 0 pending
- evaluation review states: 15 accepted
- local absolute paths removed: yes
- AI history, previews, backups, and intermediate labels included: no
- SHA-256 manifest: `datasets/stool_public/v1/checksums.sha256`

The original checking-session copy is not published because the same 15 image
frames are represented once in the reviewed independent evaluation directory.

## Reproduction entry points

- environment setup: `setup_training_windows.ps1`
- complete fixed-split run: `reproduce_stool_v1.ps1`
- optional 18-model augmentation comparison:
  `reproduce_stool_v1.ps1 -RunCrossValidation`
- generic grouped CV runner: `cross_validate_fomo.ps1`
- public dataset exporter: `laptop/export_stool_public_dataset.py`

The reproduction script verifies checksums before reading data, writes only to
the ignored `training_runs/` directory, and does not modify source images,
masks, labels, or metadata.

## Reference model

- model: `models/fomo_stool_v1.tflite`
- labels: `background`, `stool`
- size: 18,672 bytes
- SHA-256:
  `c2af1df98479dc69bf6f3a039bcff577793f11a0d0873c8eeda021818644b3fe`
- input: uint8 96x96 RGB
- output: uint8 12x12x2 FOMO grid

Machine-readable reference metrics are stored in
`reports/stool_fomo_v1_reference.json`.

## Original reference results

| Evaluation | Result |
|---|---:|
| six-fold mean F1, no augmentation | 91.42% |
| six-fold mean F1, mild | 93.32% |
| six-fold mean F1, default | 93.29% |
| fixed S06 test F1 | 94.29% |
| independent TP / FP / FN | 19 / 5 / 0 |
| independent F1 | 88.37% |

`default` was selected because its mean F1 was effectively tied with `mild`
while exact count, center localization, and false positives were better.

## Clean-worktree verification

The full fixed-split pipeline was run using only
`datasets/stool_public/v1`. It completed manifest generation, training, int8
conversion, validation threshold selection, S06 testing, independent
inference, and GT scoring.

| Item | Clean-worktree result |
|---|---:|
| epochs completed after early stopping | 23 |
| TFLite size | 18,672 bytes |
| selected validation threshold | 0.40 |
| S06 test F1 | 91.67% |
| independent TP / FP / FN | 19 / 4 / 0 |
| independent F1 | 90.48% |

Native Windows TensorFlow/oneDNN is seeded but can still produce small
run-to-run differences. A Windows TFLite calibration failure caused by an
uninitialized `READ_VARIABLE` resource was eliminated by freezing model
variables before int8 calibration. The corrected pipeline then completed
without retry.

## Automated checks

- 23 targeted training/export/validation/evaluation/ROI tests passed
- exporter duplicate-removal behavior covered by tests
- public metadata scan found no local user path or intermediate artifact path
- all 210 public image hashes are unique
- `git diff --check` passed

## Remaining release decision

The dataset has no standalone license yet. Before pushing the public data, the
repository owner should select a data license and confirm redistribution of the
captured floor images. No license was inferred or added automatically.

After that decision, this isolated branch can be committed and pushed without
touching `main` or the other working directory. A pull request can then be used
for review and conflict detection.
