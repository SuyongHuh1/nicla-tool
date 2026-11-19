# Stool low-light negative add-on v1

This add-on contains eight manually reviewed empty-floor images captured from
the live Nicla Vision setup on 2026-11-19.

- Class: background only (`expected_instances = 0`)
- Camera mount: approximately 100 mm high, 45-degree downward tilt
- Condition: low light
- Resolution: 320 x 240 JPEG
- Included: uniform or mildly graded empty floor
- Excluded: distinct cast shadows, black chassis/camera edges, visible roller
  hardware, and severe coloured sensor noise

The source capture folder is intentionally not versioned.  Only the accepted
images are included here.  These images are an optional training add-on and do
not replace the immutable `datasets/stool_public/v1` dataset.

The experiment documented in
[`docs/lowlight_negative_experiment_20261119.md`](../../../docs/lowlight_negative_experiment_20261119.md)
did not produce a model that outperformed the deployed model on the untouched
independent inference set, so no new model was deployed.
