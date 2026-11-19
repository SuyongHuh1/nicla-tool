# Low-light background experiment — 2026-11-19

## Purpose

Test whether newly captured dark empty-floor images reduce false stool
detections without changing the untouched independent inference set.

## Review and data handling

- Captured: 22 background images
- Accepted after visual review: 8
- Excluded: 14 with a distinct cast shadow, black chassis/camera edge, visible
  roller hardware, or severe coloured sensor noise
- Original stool dataset: unchanged
- Independent inference images: never trained on or edited

The accepted add-on is versioned at
`datasets/stool_lowlight_negative/v1`.  Reusable manifest assembly is provided
by `laptop/append_background_captures.py`.

## Result

| Model | Threshold | Ordinary test F1 | FP/image | Independent inference F1 |
|---|---:|---:|---:|---:|
| Existing OpenMV 4.3 model | 0.65 | 93.0% | 0.118 | **90.5%** |
| Eight clean negatives, auto threshold | 0.50 | **94.3%** | **0.088** | 88.4% |
| Eight clean negatives, deployed threshold | 0.65 | — | — | 85.7% |

The candidate improved its ordinary held-out test but regressed on the
independent inference set.  It was therefore rejected and was not copied to
the Nicla Vision.  The deployed `fomo_stool_v1_openmv43.tflite` model and
threshold `0.65` remain the baseline.

## Next collection

Repeat collection only after the camera height, tilt, fixed illumination,
roller visibility, vehicle speed, and floor materials are finalized.  Capture
balanced positive and negative low-light sessions, and reserve a physically
separate session for validation and testing.
