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

If allocation fails, investigate board memory and supported model embedding
before adopting a /rom/ model path. No embedded build is included here.
