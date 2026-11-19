"""Stream camera frames and detections over the USB virtual serial port.

Run this from the OpenMV REPL or let laptop/usb_viewer.py start it. Ctrl-C
stops the stream and returns to the REPL.
"""

import gc
import sys
import struct
import time
import pyb

try:
    import ujson as json
except ImportError:
    import json

# OpenMV keeps imported modules cached after Ctrl-C.  USB preview commonly
# takes over from main.py, so reload the camera/detector files that may have
# been updated on the board drive without requiring a physical unplug.
for _module_name in ("camlib", "detection_config", "tinyml_roi"):
    if _module_name in sys.modules:
        del sys.modules[_module_name]

import camlib
import detection_config as detection_cfg
import tinyml_roi


MAGIC = b"NVU2"
JPEG_QUALITY = 45


def write_all(usb, data):
    view = memoryview(data)
    while len(view):
        count = usb.write(view)
        if not count:
            time.sleep_ms(5)
            continue
        view = view[count:]


def main():
    usb = pyb.USB_VCP()
    cam = camlib.Camera(framesize="QVGA", pixformat="RGB565", warmup_ms=1500)
    detector = tinyml_roi.create_detector(detection_cfg)
    temporal = tinyml_roi.TemporalConsensus(
        getattr(detection_cfg, "TEMPORAL_WINDOW", 5),
        getattr(detection_cfg, "TEMPORAL_MIN_HITS", 3),
        getattr(detection_cfg, "TEMPORAL_MAX_DISTANCE_PX", 32))
    use_temporal = bool(getattr(detection_cfg, "TEMPORAL_FILTER_ENABLED", True))
    refine = bool(getattr(detection_cfg, "ROI_REFINEMENT_ENABLED", True))
    seq = 0
    fps = 0.0
    previous_ms = time.ticks_ms()
    while True:
        if not usb.isconnected():
            time.sleep_ms(50)
            continue

        image = cam.snapshot()
        captured_ms = time.ticks_ms()
        if detector.name == "tinyml_roi":
            raw = detector.detect(image, refine=refine)
            pipeline = "fomo_roi" if refine else "fomo_only"
        else:
            raw = detector.detect(image)
            pipeline = "color_demo"
        detections = temporal.update(raw) if use_temporal else raw
        jpeg = camlib.jpeg_bytes(image, JPEG_QUALITY)
        header = {
            "v": 1,
            "seq": seq,
            "ms": captured_ms,
            "w": image.width(),
            "h": image.height(),
            "det": detections,
            "detector": detector.name,
            "pipeline": pipeline,
            "roi_refine": refine,
            "roi_refine_active": pipeline == "fomo_roi",
            "temporal": use_temporal,
            "temporal_window": temporal.window,
            "temporal_min_hits": temporal.min_hits,
            "fps": round(fps, 1),
            "q": JPEG_QUALITY,
            "transport": "usb",
        }
        encoded_header = json.dumps(header).encode("utf-8")
        write_all(usb, MAGIC)
        write_all(usb, struct.pack("<III", seq, len(encoded_header), len(jpeg)))
        write_all(usb, encoded_header)
        write_all(usb, jpeg)
        seq = (seq + 1) & 0xFFFFFFFF
        now = time.ticks_ms()
        elapsed = time.ticks_diff(now, previous_ms)
        previous_ms = now
        if elapsed > 0:
            fps = 0.9 * fps + 0.1 * (1000.0 / elapsed)
        if seq % 10 == 0:
            gc.collect()


main()
