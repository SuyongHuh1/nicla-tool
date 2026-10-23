"""Wet-floor (urine / liquid) cues from LED on/off frame pairs.

Ambient light reaches the camera in both frames of a pair, so the difference
on - off keeps (mostly) only what our own LED adds. A wet film adds a strong
specular glint, dry floor adds a diffuse, uniform brightening.
"""
import cv2
import numpy as np


def lab(bgr):
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB).astype(np.float32)


def diff_map(on_bgr, off_bgr):
    """Lightness gained from the LED (0..255 scale), negatives clipped."""
    return np.clip(lab(on_bgr)[..., 0] - lab(off_bgr)[..., 0], 0, None)


def normalised_diff(on_bgr, off_bgr, blur=21):
    """Diff divided by its local median so a uniformly brighter LED spot
    (closer floor = more light) does not look like a puddle."""
    d = diff_map(on_bgr, off_bgr)
    base = cv2.medianBlur(np.clip(d, 0, 255).astype(np.uint8), blur).astype(np.float32)
    return d / (base + 4.0)


def heatmap(d, vmax=None):
    vmax = vmax or max(float(np.percentile(d, 99.5)), 1e-3)
    u8 = np.clip(d / vmax * 255, 0, 255).astype(np.uint8)
    return cv2.applyColorMap(u8, cv2.COLORMAP_INFERNO)


def roi(a, r):
    x, y, w, h = r
    return a[y:y + h, x:x + w].reshape(-1)


def separation(wet, dry, stat="mean"):
    """d' of a wet-region statistic against the dry pixel distribution."""
    sd = float(dry.std()) or 1e-6
    v = float(np.percentile(wet, 90)) if stat == "p90" else float(wet.mean())
    return abs(v - float(dry.mean())) / sd


def coverage(wet, dry, q=99.0):
    """Share of wet pixels brighter than the dry floor's q-th percentile."""
    return float((wet > np.percentile(dry, q)).mean())
