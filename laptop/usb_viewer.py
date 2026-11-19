"""Live Nicla Vision detection viewer over USB, without changing PC Wi-Fi.

By default the script interrupts the running board program and starts
nicla/usb_preview.py from the board drive. With --attach it reads an already
running USB main.py, which is the stable mode for older OpenMV firmware. The
RECORD and MASK buttons match the Wi-Fi viewer. Press Q or Escape to quit, C
to save a frame, R to record, or M to hide/show the mask.
"""

import argparse
import json
import os
import struct
import sys
import time
from collections import deque

import cv2
import numpy as np
import serial
from serial.tools import list_ports

import viewer

MAGIC = b"NVU2"
LEGACY_MAGIC = b"NVJ1"
MAX_JPEG = 2 * 1024 * 1024
MAX_HEADER = 64 * 1024


def find_nicla_port(requested=None):
    if requested:
        return requested
    ports = list(list_ports.comports())
    arduino = [p.device for p in ports if p.vid == 0x2341]
    if len(arduino) == 1:
        return arduino[0]
    if not arduino:
        raise RuntimeError("Nicla serial port not found; pass --port COMx")
    raise RuntimeError("multiple Arduino ports found: %s; pass --port" % ", ".join(arduino))


def read_exact(port, size):
    data = bytearray()
    while len(data) < size:
        chunk = port.read(size - len(data))
        if not chunk:
            raise TimeoutError("USB frame timed out")
        data.extend(chunk)
    return bytes(data)


def sync_magic(port):
    window = bytearray()
    while True:
        value = port.read(1)
        if not value:
            raise TimeoutError("no USB preview data; is usb_preview.py on the board?")
        window.extend(value)
        if len(window) > len(MAGIC):
            del window[0]
        found = bytes(window)
        if found in (MAGIC, LEGACY_MAGIC):
            return found


def start_board_preview(port):
    port.write(b"\x03\x03")
    time.sleep(0.4)
    port.reset_input_buffer()
    port.write(b"exec(open('usb_preview.py').read())\r\n")


def read_packet(port):
    magic = sync_magic(port)
    if magic == MAGIC:
        seq, header_size, size = struct.unpack("<III", read_exact(port, 12))
        if header_size < 2 or header_size > MAX_HEADER:
            raise RuntimeError("invalid USB header size %d" % header_size)
        header = json.loads(read_exact(port, header_size).decode("utf-8"))
    else:
        seq, size = struct.unpack("<II", read_exact(port, 8))
        header = {"seq": seq, "det": [], "detector": "none",
                  "pipeline": "raw", "transport": "usb", "q": None}
    if size < 32 or size > MAX_JPEG:
        raise RuntimeError("invalid JPEG size %d" % size)
    jpeg = read_exact(port, size)
    image = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise RuntimeError("invalid JPEG frame %d" % seq)
    header["seq"] = seq
    return seq, header, jpeg, image


def read_frame(port):
    """Backward-compatible raw-frame helper."""
    seq, _header, _jpeg, image = read_packet(port)
    return seq, image


class Recorder:
    def __init__(self, label):
        self.label = label
        self.directory = None
        self.meta = None
        self.count = 0
        self.video = None
        self.video_path = None

    def toggle(self):
        if self.directory:
            path = self.directory
            count = self.count
            self.meta.close()
            if self.video is not None:
                self.video.release()
            self.directory = None
            self.meta = None
            self.video = None
            video_path = self.video_path
            self.video_path = None
            return "stopped (%d frames) %s video=%s" % (
                count, path, video_path or "not-created")
        path = os.path.join("recordings", time.strftime("%Y%m%d_%H%M%S") + "_" + self.label)
        os.makedirs(os.path.join(path, "frames"), exist_ok=True)
        self.meta = open(os.path.join(path, "meta.jsonl"), "a", encoding="utf-8")
        self.directory = path
        self.count = 0
        self.video = None
        self.video_path = None
        return "recording -> %s" % path

    def write(self, header, jpeg):
        if not self.directory:
            return
        self.count += 1
        name = "%06d.jpg" % self.count
        with open(os.path.join(self.directory, "frames", name), "wb") as handle:
            handle.write(jpeg)
        self.meta.write(json.dumps({"file": name, "t_recv_ms": time.monotonic() * 1000.0,
                                    "hdr": header}, ensure_ascii=False) + "\n")
        self.meta.flush()

    def write_view(self, frame, fps=10.0):
        """Save the rendered live view, including mask, boxes, HUD and controls."""
        if not self.directory:
            return
        if self.video is None:
            height, width = frame.shape[:2]
            self.video_path = os.path.join(self.directory, "screen.mp4")
            fourcc = cv2.VideoWriter_fourcc(*"mp4v")
            self.video = cv2.VideoWriter(
                self.video_path, fourcc, max(1.0, float(fps or 10.0)),
                (width, height))
            if not self.video.isOpened():
                self.video.release()
                self.video_path = os.path.join(self.directory, "screen.avi")
                fourcc = cv2.VideoWriter_fourcc(*"MJPG")
                self.video = cv2.VideoWriter(
                    self.video_path, fourcc, max(1.0, float(fps or 10.0)),
                    (width, height))
            if not self.video.isOpened():
                raise RuntimeError("cannot create rendered recording")
        self.video.write(frame)

    def close(self):
        if self.directory:
            print(self.toggle())


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", help="Nicla COM port; auto-detected when omitted")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--frames", type=int, default=0, help="stop after N frames; 0 keeps running")
    parser.add_argument("--out", help="save the last frame to this path")
    parser.add_argument("--label", default="usb_live", help="recording/capture label")
    parser.add_argument("--scale", type=float, default=2.0, help="display zoom")
    parser.add_argument("--record", action="store_true", help="start recording immediately")
    parser.add_argument("--attach", action="store_true",
                        help="do not interrupt the board; attach to USB main.py already running")
    args = parser.parse_args(argv)

    port_name = find_nicla_port(args.port)
    ser = serial.Serial(port_name, 115200, timeout=8, write_timeout=3)
    last = None
    last_header = None
    count = 0
    show_mask = True
    recorder = Recorder(args.label)
    if args.record:
        print(recorder.toggle())
    mouse_events = deque()
    button_rects = {}

    if not args.headless:
        cv2.namedWindow("Nicla Vision USB detection", cv2.WINDOW_AUTOSIZE)

        def on_mouse(event, x, y, _flags, _param):
            if event == cv2.EVENT_LBUTTONUP:
                action = viewer.control_at(button_rects, x, y)
                if action:
                    mouse_events.append(action)

        cv2.setMouseCallback("Nicla Vision USB detection", on_mouse)
    try:
        if not args.attach:
            start_board_preview(ser)
        while not args.frames or count < args.frames:
            seq, header, jpeg, frame = read_packet(ser)
            last = frame
            last_header = header
            count += 1
            recorder.write(header, jpeg)
            if not args.headless:
                shown = frame.copy()
                if args.scale != 1.0:
                    shown = cv2.resize(shown, None, fx=args.scale, fy=args.scale,
                                       interpolation=cv2.INTER_NEAREST)
                if show_mask:
                    viewer.draw_mask_overlay(shown, header, args.scale)
                viewer.draw_overlay(shown, header, args.scale)
                lines = [
                    "%s USB frame %d | board %.1f fps | q %s" %
                    (port_name, seq, header.get("fps", 0.0), header.get("q", "-")),
                    "det %d | %s | temporal %s" %
                    (len(header.get("det", []) or []),
                     header.get("pipeline", header.get("detector", "?")),
                     "on" if header.get("temporal") else "off"),
                    "Q/Esc quit  C capture  R record  M mask",
                ]
                if recorder.directory:
                    lines.append("REC %d" % recorder.count)
                viewer.draw_hud(shown, lines)
                button_rects.clear()
                button_rects.update(viewer.draw_controls(
                    shown, bool(recorder.directory), show_mask))
                recorder.write_view(shown, header.get("fps", 10.0))
                cv2.imshow("Nicla Vision USB detection", shown)
                key = cv2.waitKey(1) & 0xFF
                action = mouse_events.popleft() if mouse_events else None
                if action == "record":
                    print(recorder.toggle())
                elif action == "mask":
                    show_mask = not show_mask
                if key in (ord("q"), 27):
                    break
                if key == ord("r"):
                    print(recorder.toggle())
                if key == ord("m"):
                    show_mask = not show_mask
                if key == ord("c"):
                    os.makedirs("captures", exist_ok=True)
                    path = os.path.join("captures", "%s_%s.jpg" %
                                        (args.label, time.strftime("%Y%m%d_%H%M%S")))
                    cv2.imwrite(path, frame)
                    print("saved", path)
        if args.out and last is not None:
            parent = os.path.dirname(os.path.abspath(args.out))
            os.makedirs(parent, exist_ok=True)
            if not cv2.imwrite(args.out, last):
                raise RuntimeError("failed to save %s" % args.out)
        if last_header:
            print("received %d frame(s) from %s: detector=%s pipeline=%s det=%d" %
                  (count, port_name, last_header.get("detector", "?"),
                   last_header.get("pipeline", "?"),
                   len(last_header.get("det", []) or [])))
        else:
            print("received %d frame(s) from %s" % (count, port_name))
        return 0
    finally:
        recorder.close()
        if not args.attach:
            try:
                ser.write(b"\x03")
            except Exception:
                pass
        ser.close()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    sys.exit(main())
