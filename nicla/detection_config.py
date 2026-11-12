"""Configuration for the TinyML -> ROI detection pipeline.

Copy the trained FOMO model and labels.txt to the Nicla drive, then set
DETECTOR_MODE to "tinyml_roi".  "auto" keeps the phase-1 colour detector as a
fallback while the model is not installed.
"""

DETECTOR_MODE = "auto"  # "auto" | "tinyml_roi" | "color_demo"

# Edge Impulse/OpenMV FOMO model.  A filesystem model normally uses the first
# path.  A model baked into custom OpenMV firmware can use a /rom/... path.
FOMO_MODEL_PATH = "fomo_stool_v1.tflite"
FOMO_LABELS_PATH = "labels.txt"
FOMO_CONFIDENCE = 0.55
FOMO_LOAD_TO_FB = True

# Runtime switches.  The laptop viewer can temporarily change these without
# rewriting this file or rebooting the board:
#   O = ROI refinement, T = temporal consensus, P = FOMO/colour comparison.
ROI_REFINEMENT_ENABLED = True
TEMPORAL_FILTER_ENABLED = True
TEMPORAL_WINDOW = 5
TEMPORAL_MIN_HITS = 3
TEMPORAL_MAX_DISTANCE_PX = 32

# Labels produced by the model are normalised before ROI refinement.
CLASS_ALIASES = {
    "poop": "stool",
    "feces": "stool",
    "faeces": "stool",
    "pee": "urine",
}

# The FOMO centroid is expanded to this class-specific ROI before estimating
# the clean-up area.  Tune these after camera height/angle calibration.
ROI_SIZES = {
    "stool": (112, 112),
    "urine": (144, 112),
}
DEFAULT_ROI_SIZE = (112, 112)

# Stool refinement reuses the phase-1 dark-brown LAB threshold.  OpenMV LAB
# ranges are L=0..100 and A/B=-128..127.
STOOL_LAB_THRESHOLDS = [(0, 45, 0, 35, 0, 45)]
STOOL_MIN_PIXELS = 120

# Transparent urine should not be trusted to a fixed colour threshold.  With
# None, the viewer shows the FOMO-centred ROI and marks it unrefined.  Enable a
# threshold only after the LED on/off experiment proves it generalises.
URINE_LAB_THRESHOLDS = None
URINE_MIN_PIXELS = 80

# Extra coverage for a roller path; a slightly oversized box is safer than a
# box that cuts off the object edge.
BBOX_PADDING_PX = 8

# Phase-1 fallback detector, used only in auto/color_demo mode.
DEMO_LAB_THRESHOLDS = STOOL_LAB_THRESHOLDS
DEMO_MIN_PIXELS = STOOL_MIN_PIXELS

