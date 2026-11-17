from pathlib import Path
import sys

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "laptop"))

import validate_stool_fomo as validate  # noqa: E402


def row(sample_id, split, shape, centers):
    return {
        "sample_id": sample_id,
        "split": split,
        "shape_id": shape,
        "group_id": shape,
        "group_field": "shape_id",
        "objects": [
            {"class_id": 1, "bbox_yolo": [x, y, 0.1, 0.1]}
            for x, y in centers
        ],
    }


def test_split_integrity_detects_shape_leakage():
    rows = [
        row("a", "train", "S01", [(0.5, 0.5)]),
        row("b", "test", "S01", [(0.5, 0.5)]),
    ]
    result = validate.split_integrity(rows)
    assert result["leakage_free"] is False
    assert result["group_id_overlap"] == ["S01"]


def test_threshold_is_selected_on_detection_f1():
    rows = [row("v1", "validation", "S05", [(0.5, 0.5)])]
    probability = np.zeros((12, 12), np.float32)
    probability[6, 6] = 0.8
    probability[1, 1] = 0.4
    threshold, sweep = validate.choose_threshold(
        rows, [probability], class_id=1, thresholds=(0.3, 0.5, 0.9))
    assert threshold == 0.5
    assert [entry["f1"] for entry in sweep] == [2 / 3, 1.0, 0.0]


def test_multiple_objects_are_matched_one_to_one():
    rows = [row("t1", "test", "S06", [(0.2, 0.2), (0.8, 0.8)])]
    probability = np.zeros((12, 12), np.float32)
    probability[2, 2] = 0.9
    probability[9, 9] = 0.85
    result = validate.evaluate_probabilities(
        rows, [probability], threshold=0.5, class_id=1)
    assert result["true_positives"] == 2
    assert result["false_positives"] == 0
    assert result["false_negatives"] == 0
    assert result["exact_count_rate"] == 1.0


def test_roi_sweep_counts_missed_detection_as_zero(tmp_path):
    image_path = tmp_path / "image.jpg"
    import cv2
    image = np.zeros((240, 320, 3), np.uint8)
    ok, encoded = cv2.imencode(".jpg", image)
    assert ok
    encoded.tofile(str(image_path))
    rows = [{
        **row("t1", "test", "S06", [(0.5, 0.5)]),
        "image": str(image_path),
    }]
    details = [{
        "sample_id": "t1",
        "matches": [],
        "predicted_centers": [],
    }]
    sweep = validate.roi_coverage_sweep(rows, details, 1, (112,))
    assert sweep[0]["matched_gt_objects"] == 0
    assert sweep[0]["mean_bbox_coverage_all_gt"] == 0.0
