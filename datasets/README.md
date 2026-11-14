# Dataset workspace

Raw viewer recordings stay in `recordings/` (gitignored). Use
`laptop/prepare_fomo_dataset.py` to sample them into `datasets/fomo/`.

- `fomo/`: full-frame images and approximate bounding boxes for the `stool`
  and `urine` FOMO classes. Every generated proposal is unreviewed.
- `segmentation/`: optional ROI images and masks. Do not populate this until
  the gates in `docs/tinyml_roi.md` show that LAB or LED-difference region
  detection is insufficient.

Do not split adjacent frames randomly. The exporter assigns an entire recording
session to one split so nearly identical frames cannot leak into validation or
test data.

