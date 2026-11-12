import os
import sys


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "nicla"))

import tinyml_roi  # noqa: E402


class Blob:
    def __init__(self, x, y, w, h, px):
        self.v = (x, y, w, h, px)

    def x(self): return self.v[0]
    def y(self): return self.v[1]
    def w(self): return self.v[2]
    def h(self): return self.v[3]
    def cx(self): return self.v[0] + self.v[2] // 2
    def cy(self): return self.v[1] + self.v[3] // 2
    def pixels(self): return self.v[4]


class Image:
    def __init__(self, blobs):
        self.blobs = blobs
        self.last_roi = None
        self.find_calls = 0

    def width(self): return 320
    def height(self): return 240

    def find_blobs(self, thresholds, roi=None, **kwargs):
        self.find_calls += 1
        self.last_roi = roi
        return self.blobs


class Model:
    api = "test"
    model_path = "fake.tflite"

    def predict(self, img):
        return [
            {"cls": "poop", "class_id": 1, "fomo_bbox": [145, 105, 16, 16],
             "cx": 153, "cy": 113, "conf": 0.91, "source": "fomo"},
            {"cls": "urine", "class_id": 2, "fomo_bbox": [40, 170, 16, 16],
             "cx": 48, "cy": 178, "conf": 0.82, "source": "fomo"},
        ]


def test_center_roi_clamps_at_edges():
    assert tinyml_roi.center_roi(3, 4, (100, 80), 320, 240) == (0, 0, 100, 80)
    assert tinyml_roi.center_roi(319, 239, (100, 80), 320, 240) == (220, 160, 100, 80)


def test_choose_blob_prefers_center_over_larger_neighbour():
    containing = Blob(145, 105, 20, 20, 200)
    larger = Blob(180, 100, 60, 60, 2000)
    assert tinyml_roi.choose_blob([larger, containing], 153, 113) is containing


def test_fomo_then_stool_lab_and_urine_roi_fallback():
    img = Image([Blob(140, 100, 30, 25, 500)])
    detector = tinyml_roi.TinyMlRoiDetector(
        Model(), aliases={"poop": "stool"},
        roi_sizes={"stool": (100, 80), "urine": (120, 90)},
        stool_thresholds=[(0, 45, 0, 35, 0, 45)], urine_thresholds=None,
        padding=5)
    stool, urine = detector.detect(img)
    assert stool["cls"] == "stool" and stool["refined"] is True
    assert stool["region_source"] == "lab" and stool["bbox"] == [135, 95, 40, 35]
    assert urine["cls"] == "urine" and urine["refined"] is False
    assert urine["region_source"] == "fomo_roi" and urine["bbox"] == urine["roi"]


def test_roi_refinement_can_be_disabled_without_disabling_fomo():
    img = Image([Blob(140, 100, 30, 25, 500)])
    detector = tinyml_roi.TinyMlRoiDetector(
        Model(), aliases={"poop": "stool"},
        roi_sizes={"stool": (100, 80), "urine": (120, 90)},
        stool_thresholds=[(0, 45, 0, 35, 0, 45)], padding=5)
    stool, urine = detector.detect(img, refine=False)
    assert img.find_calls == 0
    assert stool["source"] == "fomo" and stool["refined"] is False
    assert stool["bbox"] == stool["roi"]
    assert urine["source"] == "fomo" and urine["bbox"] == urine["roi"]


def _det(x=100, y=80, cls="stool"):
    return {"cls": cls, "cx": x, "cy": y, "bbox": [x - 10, y - 10, 20, 20]}


def test_temporal_consensus_requires_three_of_five_current_matches():
    temporal = tinyml_roi.TemporalConsensus(window=5, min_hits=3, max_distance=12)
    assert temporal.update([_det(100, 80)]) == []
    assert temporal.update([_det(105, 82)]) == []
    accepted = temporal.update([_det(108, 84)])
    assert len(accepted) == 1
    assert accepted[0]["temporal_hits"] == 3
    assert accepted[0]["temporal_window"] == 3
    assert temporal.update([]) == []  # never emit a stale detection


def test_temporal_consensus_separates_classes_and_reset():
    temporal = tinyml_roi.TemporalConsensus(window=3, min_hits=2, max_distance=10)
    assert temporal.update([_det(cls="stool")]) == []
    assert temporal.update([_det(cls="urine")]) == []
    accepted = temporal.update([_det(cls="urine")])
    assert [item["cls"] for item in accepted] == ["urine"]
    temporal.reset()
    assert temporal.update([_det(cls="urine")]) == []

