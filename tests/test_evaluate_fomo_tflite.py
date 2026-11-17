from pathlib import Path
import sys

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "laptop"))

import evaluate_fomo_tflite as evaluate  # noqa: E402


def test_decode_groups_adjacent_cells_and_maps_roi():
    heatmap = np.zeros((12, 12), np.float32)
    heatmap[5, 6] = 0.9
    heatmap[5, 7] = 0.8
    detections, top = evaluate.decode_fomo(heatmap, 0.55, 320, 240)
    assert len(detections) == 1
    assert detections[0]["cells"] == 2
    assert detections[0]["score"] == np.float32(0.9)
    assert len(detections[0]["roi_xywh"]) == 4
    assert top["score"] == np.float32(0.9)


def test_rejects_training_folder(tmp_path):
    training = tmp_path / "datasets" / "stool" / "session" / "images"
    training.mkdir(parents=True)
    try:
        evaluate.assert_inference_session(training.parent)
    except RuntimeError as error:
        assert "checking/inference" in str(error)
    else:
        raise AssertionError("training folder was accepted as inference")
