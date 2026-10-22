"""Live viewer / recorder / remote control for the Nicla stream.

  py laptop\\viewer.py --host 192.168.137.50 --label q50

Keys
  W A S D   drive (hold)          SPACE  stop
  + / -     drive speed           1 2 3  mode manual / assist / auto
  [ / ]     JPEG quality -/+      B      toggle demo blob detector
  R         start/stop recording  C      save current frame to captures/
  H         toggle help           Q/ESC  quit (writes a session summary)

Recording saves raw JPEGs (no overlay) + header JSON lines, so recordings can
be used later as training data. On exit a summary (fps, latency, round-trip)
is written to results/stream/<label>.json - that is the phase 1 Wi-Fi test.

Vehicle control is a stub on the board for now: commands are acknowledged and
shown in the HUD, but nothing moves until the vehicle UART link exists.
"""
import argparse
import json
import os
import socket
import sys
import threading
import time
from collections import deque

import numpy as np

import nvlink

GRADE_COLORS = {0: (60, 200, 60), 1: (0, 220, 255), 2: (0, 140, 255), 3: (40, 40, 230)}   # BGR
GRADE_NAMES = {0: "hard", 1: "normal", 2: "soft", 3: "liquid"}
DRIVE_HOLD_S = 0.25
CMD_RATE_HZ = 10


def now_ms():
    return time.monotonic() * 1000.0


def pct(vals, q):
    return float(np.percentile(vals, q)) if len(vals) else None


class Link:
    """Owns the socket: background receive thread + thread-safe command sending."""

    def __init__(self, sock, record_root="recordings", label="session"):
        self.sock = sock
        self.sock.settimeout(5.0)
        self.send_lock = threading.Lock()
        self.lock = threading.Lock()
        self.latest = None            # (hdr, jpg, t_recv)
        self.latest_id = 0
        self.alive = True
        self.error = None
        self.cmd_seq = 0
        self.pending_ping = {}
        self.offset_samples = deque(maxlen=20)   # (rtt, offset)
        self.rtts = []
        self.latencies = []
        self.t_frames = []
        self.bytes = 0
        self.qualities = set()
        self.last_ack = None
        self.record_root = record_root
        self.label = label
        self.rec_dir = None
        self.rec_meta = None
        self.rec_count = 0
        self.thread = threading.Thread(target=self._rx, daemon=True)
        self.thread.start()

    # ---- commands
    def send(self, cmd):
        self.cmd_seq += 1
        cmd = dict(cmd, seq=self.cmd_seq)
        if cmd["t"] == "ping":
            self.pending_ping[self.cmd_seq] = now_ms()
        try:
            with self.send_lock:
                self.sock.sendall(nvlink.encode_cmd(cmd))
        except OSError as e:
            self.error = e
            self.alive = False
        return self.cmd_seq

    def offset(self):
        if not self.offset_samples:
            return None
        return min(self.offset_samples)[1]   # sample with the smallest round trip

    # ---- receive
    def _rx(self):
        try:
            while self.alive:
                hdr, jpg = nvlink.read_message(self.sock)
                t = now_ms()
                self._account(hdr, jpg, t)
                with self.lock:
                    self.latest = (hdr, jpg, t)
                    self.latest_id += 1
                if self.rec_dir:
                    self._record(hdr, jpg, t)
        except (OSError, ConnectionError, nvlink.ProtocolError, ValueError) as e:
            if self.alive:
                self.error = e
        finally:
            self.alive = False

    def _account(self, hdr, jpg, t):
        self.t_frames.append(t)
        self.bytes += len(jpg) + 12
        if "q" in hdr:
            self.qualities.add(hdr["q"])
        if "ack" in hdr:
            self.last_ack = hdr["ack"]
        pong = hdr.get("pong")
        if pong and pong.get("seq") in self.pending_ping:
            ts = self.pending_ping.pop(pong["seq"])
            rtt = t - ts
            self.rtts.append(rtt)
            self.offset_samples.append((rtt, pong["bt"] - (ts + rtt / 2.0)))
        off = self.offset()
        if off is not None and "ms" in hdr:
            self.latencies.append(t - (hdr["ms"] - off))

    # ---- recording
    def toggle_record(self):
        if self.rec_dir:
            path = self.rec_dir
            self.rec_dir = None
            self.rec_meta.close()
            return "stopped (%d frames) %s" % (self.rec_count, path)
        d = os.path.join(self.record_root, time.strftime("%Y%m%d_%H%M%S") + "_" + self.label)
        os.makedirs(os.path.join(d, "frames"), exist_ok=True)
        self.rec_meta = open(os.path.join(d, "meta.jsonl"), "a", encoding="utf-8")
        self.rec_count = 0
        self.rec_dir = d
        return "recording -> %s" % d

    def _record(self, hdr, jpg, t):
        self.rec_count += 1
        name = "%06d.jpg" % self.rec_count
        with open(os.path.join(self.rec_dir, "frames", name), "wb") as f:
            f.write(jpg)
        self.rec_meta.write(json.dumps({"file": name, "t_recv_ms": t, "hdr": hdr}) + "\n")

    def close(self):
        self.alive = False
        if self.rec_dir:
            self.toggle_record()
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.sock.close()

    def summary(self):
        t = self.t_frames
        dur = (t[-1] - t[0]) / 1000.0 if len(t) > 1 else 0.0
        return {"frames": len(t), "seconds": round(dur, 2),
                "fps": round((len(t) - 1) / dur, 2) if dur > 0 else None,
                "kbytes_per_s": round(self.bytes / 1024.0 / dur, 1) if dur > 0 else None,
                "latency_ms_p50": pct(self.latencies, 50), "latency_ms_p95": pct(self.latencies, 95),
                "rtt_ms_p50": pct(self.rtts, 50), "rtt_ms_p95": pct(self.rtts, 95),
                "rtt_samples": len(self.rtts), "jpeg_q": sorted(self.qualities),
                "note": "latency = capture->receipt, clock offset estimated from ping/pong (+-half a frame)"}


# ------------------------------------------------------------------ drawing
def draw_overlay(img, hdr, scale=1.0):
    import cv2
    for d in hdr.get("det", []) or []:
        grade = d.get("grade")
        color = GRADE_COLORS.get(grade, (255, 0, 255))
        if "contour" in d and d["contour"]:
            pts = (np.array(d["contour"], np.float32) * scale).astype(np.int32)
            cv2.polylines(img, [pts], True, color, 2, cv2.LINE_AA)
        if "bbox" in d:
            x, y, w, h = [int(v * scale) for v in d["bbox"]]
            cv2.rectangle(img, (x, y), (x + w, y + h), color, 2)
        else:
            x, y = int(d.get("cx", 0) * scale), int(d.get("cy", 0) * scale)
        if "cx" in d:
            cv2.circle(img, (int(d["cx"] * scale), int(d["cy"] * scale)), 4, color, -1)
        parts = [GRADE_NAMES.get(grade, d.get("cls", "obj"))]
        if d.get("conf") is not None:
            parts.append("%.0f%%" % (100 * d["conf"]))
        if d.get("area_mm2") is not None:
            parts.append("%.0fmm2" % d["area_mm2"])
        elif d.get("px") is not None:
            parts.append("%dpx" % d["px"])
        if d.get("height_mm") is not None:
            parts.append("h%.0fmm" % d["height_mm"])
        txt = " ".join(parts)
        (tw, th), _ = cv2.getTextSize(txt, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
        ty = max(y - 4, th + 4)
        cv2.rectangle(img, (x, ty - th - 4), (x + tw + 6, ty + 2), color, -1)
        cv2.putText(img, txt, (x + 3, ty - 1), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 1, cv2.LINE_AA)
    return img


def draw_hud(img, lines, origin=(8, 18)):
    import cv2
    x, y = origin
    font, fs = cv2.FONT_HERSHEY_SIMPLEX, 0.45
    width = max(cv2.getTextSize(ln, font, fs, 1)[0][0] for ln in lines) if lines else 0
    x0, y0, x1, y1 = x - 6, y - 14, min(img.shape[1], x + width + 6), min(img.shape[0], y + 16 * len(lines) - 8)
    roi = img[y0:y1, x0:x1]
    roi[:] = (roi * 0.35).astype(roi.dtype)        # dark translucent panel
    for ln in lines:
        cv2.putText(img, ln, (x, y), font, fs, (255, 255, 255), 1, cv2.LINE_AA)
        y += 16


def hud_lines(link, hdr, speed, recording, show_help):
    lat = link.latencies[-1] if link.latencies else None
    rtt = link.rtts[-1] if link.rtts else None
    tof = hdr.get("tof_mm")
    lines = ["fps board %.1f | lat %s ms | rtt %s ms | q %s" % (hdr.get("fps", 0), "%.0f" % lat if lat is not None else "-",
                                                              "%.0f" % rtt if rtt is not None else "-", hdr.get("q", "-")),
             "ToF %s mm | det %d | mode %s" % (tof if tof is not None else "-", len(hdr.get("det", []) or []), hdr.get("mode", "?")),
             "vehicle %s | drive %s | speed %d%%" % (hdr.get("vehicle", "?"), hdr.get("drive"), speed)]
    if recording:
        lines.append("REC %d" % link.rec_count)
    if show_help:
        lines += ["WASD drive  SPACE stop  +/- speed  1/2/3 mode", "[ ] jpeg q  B blobs  R rec  C snap  Q quit"]
    return lines


# --------------------------------------------------------------------- main
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", required=True, help="Nicla IP (printed on its serial console; 'ap' mode is usually 192.168.4.1)")
    ap.add_argument("--port", type=int, default=5005)
    ap.add_argument("--label", default="session", help="name for the summary / recordings")
    ap.add_argument("--scale", type=float, default=2.0, help="display zoom")
    ap.add_argument("--headless", action="store_true", help="no window (for the Wi-Fi test or scripts)")
    ap.add_argument("--duration", type=float, help="stop after N seconds")
    ap.add_argument("--record", action="store_true", help="start recording immediately")
    ap.add_argument("--jpeg-q", type=int, help="ask the board for this JPEG quality at start")
    ap.add_argument("--out", default="results")
    a = ap.parse_args(argv)

    try:
        sock = nvlink.connect(a.host, a.port)
    except OSError as e:
        sys.exit("cannot connect to %s:%d (%s). Same Wi-Fi? stream_server.py running?" % (a.host, a.port, e))
    link = Link(sock, record_root="recordings", label=a.label)
    print("connected to %s:%d" % (a.host, a.port))
    if a.jpeg_q:
        link.send({"t": "set", "key": "jpeg_q", "val": a.jpeg_q})
    if a.record:
        print(link.toggle_record())

    cv2 = None
    if not a.headless:
        import cv2
        cv2.namedWindow("nicla", cv2.WINDOW_AUTOSIZE)

    speed, show_help = 50, True
    drive, last_drive_key, driving = (0, 0), 0.0, False
    last_cmd, last_ping = 0.0, 0.0
    shown_id = 0
    jpeg_q = a.jpeg_q or 50
    blobs = True
    t_start = time.monotonic()
    try:
        while link.alive:
            t = time.monotonic()
            if a.duration and t - t_start >= a.duration:
                break
            if t - last_ping >= 1.0:
                link.send({"t": "ping"})
                last_ping = t
            if t - last_cmd >= 1.0 / CMD_RATE_HZ:
                if t - last_drive_key < DRIVE_HOLD_S:
                    link.send({"t": "drive", "l": drive[0], "r": drive[1]})
                    driving = True
                elif driving:
                    link.send({"t": "stop"})
                    driving = False
                last_cmd = t

            if a.headless:
                time.sleep(0.01)
                continue

            with link.lock:
                latest, lid = link.latest, link.latest_id
            if latest and lid != shown_id:
                shown_id = lid
                hdr, jpg, _ = latest
                img = cv2.imdecode(np.frombuffer(jpg, np.uint8), cv2.IMREAD_COLOR)
                if img is not None:
                    if a.scale != 1.0:
                        img = cv2.resize(img, None, fx=a.scale, fy=a.scale, interpolation=cv2.INTER_NEAREST)
                    draw_overlay(img, hdr, a.scale)
                    draw_hud(img, hud_lines(link, hdr, speed, bool(link.rec_dir), show_help))
                    cv2.imshow("nicla", img)
                    jpeg_q = hdr.get("q", jpeg_q)
            k = cv2.waitKey(5) & 0xFF
            if k == 255:
                continue
            ch = chr(k).lower() if k < 128 else ""
            if k == 27 or ch == "q":
                break
            if ch in "wasd" and ch:
                v = speed
                drive = {"w": (v, v), "s": (-v, -v), "a": (-v, v), "d": (v, -v)}[ch]
                last_drive_key = t
            elif ch == " ":
                last_drive_key = 0.0
                link.send({"t": "stop"})
                driving = False
            elif ch in ("+", "="):
                speed = min(100, speed + 10)
            elif ch in ("-", "_"):
                speed = max(10, speed - 10)
            elif ch in ("1", "2", "3"):
                link.send({"t": "mode", "m": {"1": "manual", "2": "assist", "3": "auto"}[ch]})
            elif ch in ("[", "]"):
                jpeg_q = max(5, min(95, jpeg_q + (-10 if ch == "[" else 10)))
                link.send({"t": "set", "key": "jpeg_q", "val": jpeg_q})
            elif ch == "b":
                blobs = not blobs
                link.send({"t": "set", "key": "blobs", "val": blobs})
            elif ch == "r":
                print(link.toggle_record())
            elif ch == "c":
                with link.lock:
                    latest = link.latest
                if latest:
                    os.makedirs("captures", exist_ok=True)
                    p = os.path.join("captures", "%s_%s.jpg" % (a.label, time.strftime("%Y%m%d_%H%M%S")))
                    with open(p, "wb") as f:
                        f.write(latest[1])
                    print("saved", p)
            elif ch == "h":
                show_help = not show_help
    except KeyboardInterrupt:
        pass
    finally:
        if link.alive:
            link.send({"t": "stop"})
        link.close()
        if cv2 is not None:
            cv2.destroyAllWindows()

    if link.error:
        print("link error:", link.error)
    summ = link.summary()
    os.makedirs(os.path.join(a.out, "stream"), exist_ok=True)
    p = os.path.join(a.out, "stream", a.label + ".json")
    with open(p, "w") as f:
        json.dump(summ, f, indent=2)
    print(json.dumps(summ, indent=2))
    print("-> %s" % p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
