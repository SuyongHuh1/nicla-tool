# Model artifacts

## Current deployment: stool-only v1

- Model: fomo_stool_v1.tflite (18,672 bytes), uint8 96×96 RGB input.
- Labels in order: background, stool.
- Reference confidence threshold: 0.60.
- Provenance and metrics: ../reports/stool_fomo_v1_reference.json.

Copy fomo_stool_v1.tflite to the Nicla drive using that exact name. Copy
fomo_stool_v1_labels.txt as labels.txt beside main.py. The checked-in
nicla/labels.txt contains the same two labels. Use DETECTOR_MODE="tinyml_roi"
for hardware validation; auto can fall back to the LAB color demo.

Rebuild with reproduce_stool_v1.ps1. A retrained artifact must be paired with
its own validation-selected threshold; 0.40 in the reproduction report belongs
to that separate run, not the versioned reference model.
Measure board FPS, memory, and end-to-end behavior separately from offline F1.

## Future urine model

A stool+urine model requires new training data and validation. Deploy its model,
ordered labels and threshold together and update FOMO_MODEL_PATH explicitly.
Do not append urine to the current model's labels or interpret the UI candidate
as a trained urine detection.

## Versioned stool model and OpenMV 4.3 compatibility

- `fomo_stool_v1.tflite`: 96x96 int8 Tiny CNN-FOMO, 18,672 bytes
- `fomo_stool_v1_labels.txt`: `background`, `stool`

The versioned artifact was trained from `datasets/stool_public/v1` and is
described by `reports/stool_fomo_v1_reference.json`. Rebuild it with
`reproduce_stool_v1.ps1`. To try it on the board, copy the model as
`fomo_stool_v1.tflite` and copy the label file as `labels.txt`; do not confuse
it with a future three-class stool+urine model. The checked-in
`nicla/detection_config.py` uses these exact board-side names.

OpenMV 4.3.x uses the legacy `tf` API and directly maps camera bytes into a
signed-int8 input tensor. Rebuild a compatible artifact with
`reproduce_stool_v1.ps1 -OpenMv43Compatible`; this moves `[-1, 1]`
normalization outside the TFLite graph and exports signed-int8 input/output so
the graph starts with `CONV_2D` instead of preprocessing conversion operators.

The locally validated compatibility artifact is
`fomo_stool_v1_openmv43.tflite` (17,640 bytes). Its validation-selected
confidence threshold is `0.65`; keep the original 18,672-byte model as the
host/reference artifact rather than deploying it to OpenMV 4.3.x.

If allocation fails, investigate board memory and supported model embedding
before adopting a /rom/ model path. No embedded build is included here.
