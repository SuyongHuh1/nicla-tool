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

    def width(self): return 320
    def height(self): return 240

    def find_blobs(self, thresholds, roi=None, **kwargs):
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

