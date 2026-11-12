# Model artifacts

Train one FOMO object-detection model with labels in this order:

1. `background`
2. `stool`
3. `urine`

Keep exported `.tflite` files out of git by default. For filesystem loading,
copy the final model to the Nicla drive as `fomo_stool_urine.tflite` beside
`main.py` and `labels.txt`. If the board reports an allocation error, export or
build OpenMV firmware with the model embedded and set `FOMO_MODEL_PATH` in
`nicla/detection_config.py` to the resulting `/rom/...tflite` path.

The board header reports `detector=tinyml_roi` only when the model loaded. In
`auto` mode it reports `color_demo` when it fell back to the phase-1 LAB test.

## Reproducible stool-only v1 model

- `fomo_stool_v1.tflite`: 96x96 int8 Tiny CNN-FOMO, 18,672 bytes
- `fomo_stool_v1_labels.txt`: `background`, `stool`

The versioned artifact was trained from `datasets/stool_public/v1` and is
described by `reports/stool_fomo_v1_reference.json`. Rebuild it with
`reproduce_stool_v1.ps1`. To try it on the board, copy the model as
`fomo_stool_v1.tflite` and copy the label file as `labels.txt`; do not confuse
it with a future three-class stool+urine model. The checked-in
`nicla/detection_config.py` uses these exact board-side names.

