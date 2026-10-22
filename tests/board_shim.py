"""CPython stand-ins for OpenMV board modules so nicla/*.py can run in tests.

Only the API surface used by our scripts is faked. This catches Python-level
bugs (typos, wrong calls, protocol mismatches) - not firmware behaviour.
"""
import sys
import time
import types

import cv2
import numpy as np

_T0 = time.monotonic()


def _ticks_ms():
    return int((time.monotonic() - _T0) * 1000) & 0x3FFFFFFF


time.ticks_ms = _ticks_ms
time.ticks_diff = lambda a, b: a - b
time.sleep_ms = lambda ms: time.sleep(ms / 1000.0)


class _Blob:
    def __init__(self, x, y, w, h, cx, cy, px):
        self._v = (x, y, w, h, cx, cy, px)

    def x(self): return self._v[0]
    def y(self): return self._v[1]
    def w(self): return self._v[2]
    def h(self): return self._v[3]
    def cx(self): return self._v[4]
    def cy(self): return self._v[5]
    def pixels(self): return self._v[6]


class _Stats:
    def __init__(self, l):
        self._m, self._s = float(l.mean()), float(l.std())

    def l_mean(self): return int(self._m)
    def l_stdev(self): return int(self._s)


class _Jpeg:
    def __init__(self, data): self._d = data
    def bytearray(self): return bytearray(self._d)


class Image:
    def __init__(self, bgr): self.bgr = bgr
    def width(self): return self.bgr.shape[1]
    def height(self): return self.bgr.shape[0]

    def to_jpeg(self, quality=90, copy=False):
        ok, j = cv2.imencode(".jpg", self.bgr, [cv2.IMWRITE_JPEG_QUALITY, int(quality)])
        return _Jpeg(j.tobytes())

    def find_blobs(self, thresholds, pixels_threshold=10, area_threshold=10, merge=False):
        lab = cv2.cvtColor(self.bgr, cv2.COLOR_BGR2LAB).astype(np.float32)
        L = lab[..., 0] * 100 / 255
        lmin, lmax = thresholds[0][0], thresholds[0][1]
        mask = ((L >= lmin) & (L <= lmax)).astype(np.uint8)
        n, _, st, c = cv2.connectedComponentsWithStats(mask)
        return [_Blob(int(st[i][0]), int(st[i][1]), int(st[i][2]), int(st[i][3]), int(c[i][0]), int(c[i][1]), int(st[i][4]))
                for i in range(1, n) if st[i][4] >= pixels_threshold]

    def get_statistics(self, roi=None):
        x, y, w, h = roi or (0, 0, self.width(), self.height())
        lab = cv2.cvtColor(self.bgr[y:y + h, x:x + w], cv2.COLOR_BGR2LAB)
        return _Stats(lab[..., 0].astype(np.float32) * 100 / 255)


class _CSI:
    def __init__(self):
        self.n = 0
        self.exp, self.gain, self.wb = 12000, 6.0, (1.0, 0.0, 2.0)

    def reset(self): pass
    def pixformat(self, v): pass
    def framesize(self, v): pass

    def snapshot(self, time=-1, frames=-1):
        if time > 0:
            return None
        self.n += 1
        img = np.full((240, 320, 3), (120, 165, 200), np.uint8)
        cx = 160 + int(60 * np.sin(self.n / 10))
        cv2.circle(img, (cx, 120), 22, (30, 55, 90), -1)
        return Image(img)

    def exposure_us(self): return self.exp
    def gain_db(self): return self.gain
    def rgb_gain_db(self): return self.wb
    def auto_gain(self, en, gain_db=None): pass
    def auto_whitebal(self, en, rgb_gain_db=None): pass
    def auto_exposure(self, en, exposure_us=None): pass


def install(wifi_mode="sta"):
    csi = types.ModuleType("csi")
    csi.CSI = _CSI
    csi.RGB565, csi.GRAYSCALE, csi.QVGA, csi.QQVGA = 1, 2, 3, 4
    sys.modules["csi"] = csi

    machine = types.ModuleType("machine")

    class LED:
        def __init__(self, name): pass
        def on(self): pass
        def off(self): pass
    machine.LED = LED
    machine.I2C = lambda n: ("i2c", n)
    sys.modules["machine"] = machine

    vl = types.ModuleType("vl53l1x")

    class VL53L1X:
        def __init__(self, bus): self.rng = np.random.default_rng(0)
        def read(self): return int(150 + self.rng.normal(0, 1.5))
    vl.VL53L1X = VL53L1X
    sys.modules["vl53l1x"] = vl

    net = types.ModuleType("network")
    net.STA_IF, net.AP_IF = 0, 1

    class WLAN:
        def __init__(self, i): pass
        def active(self, v): pass
        def connect(self, s, p): pass
        def config(self, **kw): pass
        def isconnected(self): return True
        def ipconfig(self, k): return ("127.0.0.1", "255.0.0.0")
    net.WLAN = WLAN
    sys.modules["network"] = net

    import gc
    if not hasattr(gc, "mem_free"):
        gc.mem_free = lambda: 400000

    cfg = types.ModuleType("wifi_config")
    cfg.WIFI_MODE, cfg.WIFI_SSID, cfg.WIFI_PASS = wifi_mode, "x", "y"
    cfg.AP_SSID, cfg.AP_PASS = "nicla-cam", "nicla1234"
    sys.modules["wifi_config"] = cfg
