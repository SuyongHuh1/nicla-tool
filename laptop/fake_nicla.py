"""Simulated Nicla stream_server for trying the viewer without hardware.

  py laptop\\fake_nicla.py              (listens on 127.0.0.1:5005)
  py laptop\\viewer.py --host 127.0.0.1

Sends synthetic 320x240 frames (a brown blob drifting over a wooden floor,
plus a still, nearly invisible puddle that glints when the illumination LED
is on) with the same header fields and command handling as
nicla/stream_server.py.
"""
import argparse
import socket
import sys
import threading
import time

import cv2
import numpy as np

import nvlink

MODES = ("manual", "assist", "auto")
ILLUM_MODES = ("off", "on", "alt")
PUDDLE = ((70, 190), (30, 14))   # centre, half axes (px)


class FakeBoard:
    def __init__(self, fps=10.0, w=320, h=240, seed=0):
        self.fps, self.w, self.h = fps, w, h
        self.rng = np.random.default_rng(seed)
        self.t0 = time.monotonic()
        yy, xx = np.mgrid[0:h, 0:w]
        grain = (np.sin(xx / 7.0 + np.sin(yy / 23.0) * 3) * 12).astype(np.int16)
        base = np.zeros((h, w, 3), np.int16)
        base[:] = (120, 165, 200)          # light wood, BGR
        self.floor = np.clip(base + grain[..., None], 0, 255).astype(np.uint8)
        self.state = {"mode": "manual", "vehicle": "not_connected", "last_drive": None,
                      "jpeg_q": 50, "tof_every": 3, "blobs": True, "illum": "off", "settle": 1}
        # fixed specular pattern inside the puddle (where the LED glints)
        pm = np.zeros((h, w), np.uint8)
        cv2.ellipse(pm, PUDDLE[0], PUDDLE[1], 0, 0, 360, 1, -1)
        self.puddle = pm.astype(bool)
        glint = self.rng.random((h, w)) < 0.35
        self.glint = self.puddle & glint

    def ms(self):
        return int((time.monotonic() - self.t0) * 1000)

    def frame(self, seq, led=False):
        img = self.floor.copy()
        # puddle: barely darker and a touch more yellow with ambient light only
        img[self.puddle] = np.clip(img[self.puddle].astype(np.int16) + (-2, -2, -2), 0, 255).astype(np.uint8)
        t = seq / self.fps
        cx = int(self.w / 2 + 80 * np.sin(t * 0.6))
        cy = int(self.h / 2 + 40 * np.sin(t * 0.9))
        cv2.ellipse(img, (cx, cy), (28, 18), (t * 20) % 180, 0, 360, (30, 55, 90), -1)
        if led:
            img = cv2.add(img, (22, 22, 22, 0))           # diffuse LED light on everything
            img[self.glint] = (235, 240, 240)             # specular glints on the wet film
        noise = self.rng.integers(-6, 7, img.shape, dtype=np.int16)
        img = np.clip(img.astype(np.int16) + noise, 0, 255).astype(np.uint8)
        dets = []
        if self.state["blobs"]:
            lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
            mask = (lab[..., 0] < 115).astype(np.uint8)
            n, _, st, cent = cv2.connectedComponentsWithStats(mask)
            for i in range(1, n):
                x, y, w, h, area = st[i]
                if area >= 120:
                    dets.append({"cls": "blob", "bbox": [int(x), int(y), int(w), int(h)],
                                 "cx": int(cent[i][0]), "cy": int(cent[i][1]), "px": int(area)})
        tof = int(150 - 15 * (abs(cx - self.w / 2) < 30 and abs(cy - self.h / 2) < 30) + self.rng.normal(0, 1.5))
        return img, dets, tof

    def handle(self, cmd, replies):
        t = cmd.get("t")
        if t == "ping":
            replies["pong"] = {"seq": cmd.get("seq"), "bt": self.ms()}
        elif t == "drive":
            self.state["last_drive"] = [int(cmd.get("l", 0)), int(cmd.get("r", 0))]
            replies["ack"] = cmd.get("seq")
        elif t == "stop":
            self.state["last_drive"] = [0, 0]
            replies["ack"] = cmd.get("seq")
        elif t == "mode":
            if cmd.get("m") in MODES:
                self.state["mode"] = cmd["m"]
            replies["ack"] = cmd.get("seq")
        elif t == "set":
            k, v = cmd.get("key"), cmd.get("val")
            if k == "jpeg_q":
                self.state[k] = max(5, min(95, int(v)))
            elif k == "tof_every":
                self.state[k] = max(1, min(100, int(v)))
            elif k == "blobs":
                self.state[k] = bool(v)
            elif k == "illum" and v in ILLUM_MODES:
                self.state[k] = v
            elif k == "settle":
                self.state[k] = max(0, min(3, int(v)))
            replies["ack"] = cmd.get("seq")
        else:
            replies["err"] = "unknown command"

    def serve(self, client, stop_event):
        client.settimeout(0.0)
        reader = nvlink.LineReader()
        seq = 0
        period = 1.0 / self.fps
        nxt = time.monotonic()
        while not stop_event.is_set():
            replies = {}
            try:
                data = client.recv(512)
                if data == b"":
                    return
                for cmd in reader.feed(data):
                    self.handle(cmd, replies)
            except BlockingIOError:
                pass
            mode = self.state["illum"]
            led = (seq % 2 == 0) if mode == "alt" else (mode == "on")
            img, dets, tof = self.frame(seq, led)
            t_cap = self.ms()
            ok, jpg = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, self.state["jpeg_q"]])
            hdr = {"v": 1, "seq": seq, "ms": t_cap, "w": self.w, "h": self.h, "tof_mm": tof, "det": dets,
                   "mode": self.state["mode"], "vehicle": self.state["vehicle"], "drive": self.state["last_drive"],
                   "fps": self.fps, "q": self.state["jpeg_q"], "led": int(led), "illum": mode}
            if seq % 30 == 0:
                hdr["cam"] = {"locked": True, "exp_us": 10000, "gain_db": 6.0, "wb": None, "lock_errors": [], "fake": True}
            hdr.update(replies)
            client.settimeout(5.0)
            nvlink.send_message(client, hdr, jpg.tobytes())
            client.settimeout(0.0)
            seq += 1
            nxt += period
            time.sleep(max(0.0, nxt - time.monotonic()))


def run_server(host, port, fps, stop_event, ready=None):
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((host, port))
    srv.listen(1)
    srv.settimeout(0.5)
    if ready is not None:
        ready.append(srv.getsockname()[1])
    board = FakeBoard(fps=fps)
    try:
        while not stop_event.is_set():
            try:
                client, addr = srv.accept()
            except socket.timeout:
                continue
            try:
                board.serve(client, stop_event)
            except OSError:
                pass
            finally:
                client.close()
    finally:
        srv.close()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=5005)
    ap.add_argument("--fps", type=float, default=10.0)
    a = ap.parse_args(argv)
    stop = threading.Event()
    print("fake nicla on %s:%d (Ctrl+C to stop)" % (a.host, a.port))
    try:
        run_server(a.host, a.port, a.fps, stop)
    except KeyboardInterrupt:
        stop.set()
    return 0


if __name__ == "__main__":
    sys.exit(main())
