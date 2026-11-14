"""TinyML-first detection with class-specific ROI refinement on OpenMV.

The FOMO model answers "what is it and where is its centre?".  Refinement
answers "which nearby pixels should the roller cover?".  Stool can initially
reuse a LAB colour blob.  Urine deliberately falls back to a visible ROI until
LED-difference experiments show that a region algorithm is reliable.

This module supports the current OpenMV ``ml.Model`` API and the legacy
``tf.load(...).detect`` API used by older Nicla Vision firmware.
"""

import math


def _read_labels(path):
    labels = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                labels.append(line)
    return labels


def _normalise_score(value):
    value = float(value)
    return value / 255.0 if value > 1.0 else value


def center_roi(cx, cy, size, image_w, image_h):
    """Return a clamped (x, y, w, h) ROI centred on a FOMO detection."""
    if isinstance(size, int):
        rw = rh = size
    else:
        rw, rh = int(size[0]), int(size[1])
    rw, rh = min(rw, image_w), min(rh, image_h)
    x = max(0, min(image_w - rw, int(cx) - rw // 2))
    y = max(0, min(image_h - rh, int(cy) - rh // 2))
    return (x, y, rw, rh)


def _blob_rect(blob):
    return (int(blob.x()), int(blob.y()), int(blob.w()), int(blob.h()))


def _distance_to_rect_sq(cx, cy, rect):
    x, y, w, h = rect
    nx = min(max(cx, x), x + w)
    ny = min(max(cy, y), y + h)
    return (cx - nx) ** 2 + (cy - ny) ** 2


def choose_blob(blobs, cx, cy):
    """Prefer a blob containing the FOMO centre, otherwise the nearest one."""
    best = None
    best_key = None
    for blob in blobs:
        rect = _blob_rect(blob)
        distance = _distance_to_rect_sq(cx, cy, rect)
        pixels = int(blob.pixels())
        key = (distance, -pixels)
        if best_key is None or key < best_key:
            best, best_key = blob, key
    return best


def padded_rect(rect, padding, image_w, image_h):
    x, y, w, h = [int(v) for v in rect]
    p = max(0, int(padding))
    x0, y0 = max(0, x - p), max(0, y - p)
    x1, y1 = min(image_w, x + w + p), min(image_h, y + h + p)
    return (x0, y0, x1 - x0, y1 - y0)


class FomoModel:
    """Small compatibility wrapper for new and legacy OpenMV ML APIs."""

    def __init__(self, model_path, labels_path, threshold=0.55, load_to_fb=True):
        self.model_path = model_path
        self.threshold = float(threshold)
        self.labels = _read_labels(labels_path)
        self.api = None
        self.model = None

        ml_error = None
        try:
            import ml
            from ml.postprocessing.edgeimpulse import Fomo
            self.model = ml.Model(model_path, load_to_fb=load_to_fb,
                                  postprocess=Fomo(threshold=self.threshold))
            embedded_labels = getattr(self.model, "labels", None)
            if embedded_labels:
                self.labels = list(embedded_labels)
            self.api = "ml"
            return
        except Exception as e:
            ml_error = e

        try:
            import tf
            self.model = tf.load(model_path, load_to_fb=load_to_fb)
            if not hasattr(self.model, "detect"):
                raise RuntimeError("legacy model has no detect()")
            self.api = "tf"
        except Exception as e:
            raise RuntimeError("cannot load FOMO model with ml (%s) or tf (%s)" % (ml_error, e))

    def _label(self, index):
        return self.labels[index] if index < len(self.labels) else "class_%d" % index

    def predict(self, img):
        out = []
        if self.api == "ml":
            predictions = self.model.predict([img])
            for class_id, detections in enumerate(predictions):
                if class_id == 0:
                    continue
                for rect, score in detections:
                    x, y, w, h = [int(v) for v in rect]
                    out.append(self._candidate(class_id, x, y, w, h, score))
        else:
            lo = int(math.ceil(self.threshold * 255))
            predictions = self.model.detect(img, thresholds=[(lo, 255)])
            for class_id, detections in enumerate(predictions):
                if class_id == 0:
                    continue
                for detection in detections:
                    x, y, w, h = [int(v) for v in detection.rect()]
                    score = detection.output() if hasattr(detection, "output") else self.threshold
                    out.append(self._candidate(class_id, x, y, w, h, score))
        return out

    def _candidate(self, class_id, x, y, w, h, score):
        return {"cls": self._label(class_id), "class_id": int(class_id),
                "fomo_bbox": [x, y, w, h], "cx": int(x + w / 2),
                "cy": int(y + h / 2), "conf": _normalise_score(score),
                "source": "fomo"}


class TinyMlRoiDetector:
    name = "tinyml_roi"

    def __init__(self, model, aliases=None, roi_sizes=None, default_roi=(112, 112),
                 stool_thresholds=None, stool_min_pixels=120,
                 urine_thresholds=None, urine_min_pixels=80, padding=8):
        self.model = model
        self.aliases = aliases or {}
        self.roi_sizes = roi_sizes or {}
        self.default_roi = default_roi
        self.thresholds = {"stool": stool_thresholds, "urine": urine_thresholds}
        self.min_pixels = {"stool": stool_min_pixels, "urine": urine_min_pixels}
        self.padding = padding

    def describe(self):
        return {"name": self.name, "api": self.model.api,
                "model": self.model.model_path}

    def detect(self, img, refine=True):
        results = []
        iw, ih = int(img.width()), int(img.height())
        for candidate in self.model.predict(img):
            label = self.aliases.get(candidate["cls"], candidate["cls"])
            candidate["cls"] = label
            roi = center_roi(candidate["cx"], candidate["cy"],
                             self.roi_sizes.get(label, self.default_roi), iw, ih)
            candidate["roi"] = list(roi)
            candidate["bbox"] = list(roi)
            candidate["refined"] = False
            candidate["region_source"] = "fomo_roi"

            thresholds = self.thresholds.get(label)
            if refine and thresholds:
                blobs = img.find_blobs(thresholds, roi=roi,
                                       pixels_threshold=self.min_pixels.get(label, 80),
                                       area_threshold=self.min_pixels.get(label, 80), merge=True)
                blob = choose_blob(blobs, candidate["cx"], candidate["cy"])
                if blob is not None:
                    rect = padded_rect(_blob_rect(blob), self.padding, iw, ih)
                    candidate["bbox"] = list(rect)
                    candidate["px"] = int(blob.pixels())
                    candidate["refined"] = True
                    candidate["region_source"] = "lab"
            results.append(candidate)
        return results


class TemporalConsensus:
    """Keep current detections that persist in enough recent frames.

    Matching uses class and centre distance.  Only a detection present in the
    current frame can be emitted, so an object disappearing never leaves a
    stale box on screen.  The implementation intentionally avoids CPython-only
    helpers because this module also runs on OpenMV MicroPython.
    """

    def __init__(self, window=5, min_hits=3, max_distance=32):
        self.window = max(1, int(window))
        self.min_hits = max(1, min(int(min_hits), self.window))
        self.max_distance_sq = max(0, int(max_distance)) ** 2
        self.history = []

    def reset(self):
        self.history = []

    @staticmethod
    def _point(detection):
        return (detection.get("cls"), int(detection.get("cx", 0)),
                int(detection.get("cy", 0)))

    def _frame_matches(self, frame, cls, cx, cy):
        for other_cls, other_x, other_y in frame:
            if other_cls != cls:
                continue
            dx, dy = cx - other_x, cy - other_y
            if dx * dx + dy * dy <= self.max_distance_sq:
                return True
        return False

    def update(self, detections):
        detections = detections or []
        self.history.append([self._point(item) for item in detections])
        if len(self.history) > self.window:
            self.history.pop(0)

        accepted = []
        for detection in detections:
            cls, cx, cy = self._point(detection)
            hits = 0
            for frame in self.history:
                if self._frame_matches(frame, cls, cx, cy):
                    hits += 1
            if hits >= self.min_hits:
                item = dict(detection)
                item["temporal_hits"] = hits
                item["temporal_window"] = len(self.history)
                accepted.append(item)
        return accepted


class ColorDemoDetector:
    name = "color_demo"

    def __init__(self, thresholds, min_pixels=120, load_error=None):
        self.thresholds = thresholds
        self.min_pixels = min_pixels
        self.load_error = load_error

    def describe(self):
        info = {"name": self.name}
        if self.load_error:
            info["fallback_reason"] = str(self.load_error)
        return info

    def detect(self, img):
        out = []
        for blob in img.find_blobs(self.thresholds, pixels_threshold=self.min_pixels,
                                   area_threshold=self.min_pixels, merge=True):
            out.append({"cls": "blob", "bbox": list(_blob_rect(blob)),
                        "cx": int(blob.cx()), "cy": int(blob.cy()),
                        "px": int(blob.pixels()), "source": "lab_demo",
                        "region_source": "lab", "refined": True})
            if len(out) >= 8:
                break
        return out


def create_detector(config):
    mode = getattr(config, "DETECTOR_MODE", "auto")
    if mode == "color_demo":
        return ColorDemoDetector(config.DEMO_LAB_THRESHOLDS, config.DEMO_MIN_PIXELS)
    try:
        model = FomoModel(config.FOMO_MODEL_PATH, config.FOMO_LABELS_PATH,
                          config.FOMO_CONFIDENCE, config.FOMO_LOAD_TO_FB)
        return TinyMlRoiDetector(
            model, aliases=config.CLASS_ALIASES, roi_sizes=config.ROI_SIZES,
            default_roi=config.DEFAULT_ROI_SIZE,
            stool_thresholds=config.STOOL_LAB_THRESHOLDS,
            stool_min_pixels=config.STOOL_MIN_PIXELS,
            urine_thresholds=config.URINE_LAB_THRESHOLDS,
            urine_min_pixels=config.URINE_MIN_PIXELS,
            padding=config.BBOX_PADDING_PX)
    except Exception as e:
        if mode == "tinyml_roi":
            raise
        return ColorDemoDetector(config.DEMO_LAB_THRESHOLDS,
                                 config.DEMO_MIN_PIXELS, load_error=e)
