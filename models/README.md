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

