# Data card: Stool FOMO v1

## Summary

Stool FOMO v1 contains close-range Arduino Nicla Vision frames for training a
small centroid detector and evaluating a TinyML-first, color-refined ROI
pipeline. The dataset contains stool only; urine is not part of v1.

## Composition

| Split | Images | Physical groups | Purpose |
|---|---:|---|---|
| Training session | 195 | S01-S06 plus one empty baseline | grouped training, validation, test, and cross-validation |
| Independent evaluation | 15 | mixed/unseen arrangements | final read-only evaluation |

The training labels contain 53 accepted and 142 manually corrected samples.
All 15 independent evaluation samples were manually accepted after review.
There are no exact duplicate image hashes within or across the two sets.

## Capture setup

- camera: Arduino Nicla Vision
- image size: 320x240
- approximate camera height: 8 cm above the floor
- approximate camera angle: 45 degrees
- approximate center reference distance: 9 cm
- variations: physical stool shape, position, 90-degree orientation steps,
  partial edge clipping, and floor material

These measurements describe the collection setup and are not a calibrated
guarantee. The public metadata retains capture conditions but removes local
absolute paths and intermediate artifact references.

## Annotation policy

Human-reviewed masks include only the visible stool body. Cast shadows are not
part of the foreground mask. Final box labels are derived from the reviewed
foreground extent. `accepted` and `corrected` are both final review states;
`corrected` preserves the fact that a person changed the initial proposal.

## Leakage controls

- all frames of the same physical stool stay in the same group
- leave-one-stool-out cross-validation uses one group for test, one different
  group for validation, and the remaining four groups for training
- the fixed reference split is S01-S04 train, S05 validation, S06 test
- independent evaluation frames are never augmented or used to select the
  threshold

## Intended use

- reproduce the v1 Tiny CNN-FOMO training and evaluation
- prototype stool-centroid detection on Nicla Vision
- study ROI-based color refinement after a TinyML center proposal

This dataset is not sufficient to claim unrestricted real-world autonomous
cleaning performance.

## Known limitations

- only six physical stool groups are present in the training session
- independent evaluation has 15 frames and no dedicated empty-floor set
- collection is close-range and indoors under a limited range of lighting
- false positives and duplicate detections remain more common than misses
- board FPS, memory, temperature, and moving-vehicle behavior require separate
  hardware validation
- urine and transparent-liquid detection are not represented

## Privacy and provenance

The exported records contain no local absolute paths, account names, Wi-Fi
credentials, or intermediate review history. Images are close-up floor views,
but they should still receive a final visual privacy check before public
release.

## License

No standalone dataset license has been selected yet. Before merging this data
into a public branch, the repository owner should add an explicit data license
and confirm that the captured images may be redistributed.
