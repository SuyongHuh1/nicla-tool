# stream_server.py - Wi-Fi camera stream + detection results + command channel.
#
# The laptop runs laptop/viewer.py, which connects to TCP port 5005, shows the
# video with detection overlays, records, and sends keyboard commands back.
# Protocol: see nicla/nvproto.py and docs/protocol.md.
#
# Files that must be on the board drive: main.py (this file), camlib.py,
# nvproto.py, wifi_config.py.
#
# Phase 1: detections come from a simple colour-blob detector (DEMO_BLOBS) so
# the overlay pipeline can be tested now. Phase 4 replaces detect() with
# FOMO + the firmness classifier.
#
# Vehicle control is NOT implemented yet: drive/stop commands are acknowledged
# and stored in `state`, and vehicle_send() is the single place where the
# vehicle team's UART code will go.

import time
import gc
import network
import socket
import select

import camlib
import nvproto

try:
    import wifi_config as cfg
except ImportError:
    raise SystemExit("wifi_config.py missing: copy wifi_config_example.py to the board as wifi_config.py")

# ---------------------------------------------------------------- settings
PORT = 5005
FRAMESIZE = "QVGA"          # 320x240
JPEG_QUALITY = 50           # adjustable live from the viewer ([ and ] keys)
TOF_EVERY = 3               # read ToF every N frames (the read blocks for a while)
LOCK_CAMERA = True          # freeze exposure / gain / white balance after warm-up
DEMO_BLOBS = True           # phase-1 stand-in detector
# LAB threshold (L_min, L_max, A_min, A_max, B_min, B_max) for dark brown objects.
# Tune with OpenMV IDE: Tools > Machine Vision > Threshold Editor.
BLOB_LAB = (0, 45, 0, 35, 0, 45)
BLOB_MIN_PIXELS = 120
MODES = ("manual", "assist", "auto")
SETTABLE = ("jpeg_q", "tof_every", "blobs")
# -------------------------------------------------------------------------

led = camlib.Led("LED_BLUE")
state = {
    "mode": "manual",
    "vehicle": "not_connected",
    "last_drive": None,      # (left, right) in percent, last command received
    "last_cmd_ms": None,
    "jpeg_q": JPEG_QUALITY,
    "tof_every": TOF_EVERY,
    "blobs": DEMO_BLOBS,
}


def wifi_up():
    mode = getattr(cfg, "WIFI_MODE", "sta")
    if mode == "ap":
        wlan = network.WLAN(network.AP_IF)
        wlan.config(ssid=cfg.AP_SSID, key=cfg.AP_PASS)
        wlan.active(True)
    else:
        wlan = network.WLAN(network.STA_IF)
        wlan.active(True)
        wlan.connect(cfg.WIFI_SSID, cfg.WIFI_PASS)
        t0 = time.ticks_ms()
        while not wlan.isconnected():
            led.toggle()
            time.sleep_ms(250)
            if time.ticks_diff(time.ticks_ms(), t0) > 30000:
                raise SystemExit("Wi-Fi connect timeout (2.4 GHz WPA2-PSK only)")
    try:
        ip = wlan.ipconfig("addr4")[0]
    except Exception:
        ip = wlan.ifconfig()[0]
    return ip


# ------------------------------------------------------------ vehicle stub
def vehicle_send(left, right):
    """Single hook for the vehicle team. Planned UART line protocol:
         'M,<left>,<right>\\n'  (percent, -100..100)   'S\\n' (stop)
    Until then this only records the command."""
    state["last_drive"] = (left, right)
    state["last_cmd_ms"] = time.ticks_ms()


def vehicle_stop():
    vehicle_send(0, 0)


# --------------------------------------------------------------- commands
def clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


def handle(cmd, replies):
    t = cmd.get("t")
    if t == "ping":
        replies["pong"] = {"seq": cmd.get("seq"), "bt": time.ticks_ms()}
    elif t == "drive":
        vehicle_send(clamp(int(cmd.get("l", 0)), -100, 100), clamp(int(cmd.get("r", 0)), -100, 100))
        replies["ack"] = cmd.get("seq")
    elif t == "stop":
        vehicle_stop()
        replies["ack"] = cmd.get("seq")
    elif t == "mode":
        if cmd.get("m") in MODES:
            state["mode"] = cmd["m"]
        replies["ack"] = cmd.get("seq")
    elif t == "set":
        k = cmd.get("key")
        if k in SETTABLE:
            v = cmd.get("val")
            if k == "jpeg_q":
                v = clamp(int(v), 5, 95)
            elif k == "tof_every":
                v = clamp(int(v), 1, 100)
            else:
                v = bool(v)
            state[k] = v
        replies["ack"] = cmd.get("seq")
    else:
        replies["err"] = "unknown command"


# -------------------------------------------------------------- detection
def detect(img):
    """Returns a list of detection dicts (format: docs/protocol.md)."""
    if not state["blobs"]:
        return []
    out = []
    for b in img.find_blobs([BLOB_LAB], pixels_threshold=BLOB_MIN_PIXELS,
                            area_threshold=BLOB_MIN_PIXELS, merge=True):
        out.append({"cls": "blob", "bbox": [b.x(), b.y(), b.w(), b.h()],
                    "cx": b.cx(), "cy": b.cy(), "px": b.pixels()})
        if len(out) >= 8:
            break
    return out


# ------------------------------------------------------------------ serve
def serve(client, cam, tof, cam_info):
    client.settimeout(3.0)
    poller = select.poll()
    poller.register(client, select.POLLIN)
    reader = nvproto.LineReader()
    seq = 0
    tof_mm = None
    fps = 0.0
    t_prev = time.ticks_ms()
    while True:
        replies = {}
        for ev in poller.poll(0):
            flags = ev[1]
            if flags & (select.POLLHUP | select.POLLERR):
                raise OSError("client hung up")
            data = client.recv(512)
            if not data:
                raise OSError("client closed")
            for cmd in reader.feed(data):
                handle(cmd, replies)

        img = cam.snapshot()
        t_cap = time.ticks_ms()
        if seq % state["tof_every"] == 0:
            tof_mm = camlib.tof_read(tof)
        dets = detect(img)
        jpg = camlib.jpeg_bytes(img, state["jpeg_q"])

        hdr = {"v": nvproto.PROTO_VERSION, "seq": seq, "ms": t_cap,
               "w": img.width(), "h": img.height(), "tof_mm": tof_mm,
               "det": dets, "mode": state["mode"], "vehicle": state["vehicle"],
               "drive": state["last_drive"], "fps": round(fps, 1), "q": state["jpeg_q"]}
        if seq % 30 == 0:
            hdr["cam"] = cam_info
            hdr["mem"] = gc.mem_free()
        hdr.update(replies)
        client.sendall(nvproto.pack_prefix(hdr, len(jpg)))
        client.sendall(jpg)

        seq += 1
        now = time.ticks_ms()
        dt = time.ticks_diff(now, t_prev)
        t_prev = now
        if dt > 0:
            fps = 0.9 * fps + 0.1 * (1000.0 / dt)
        if seq % 10 == 0:
            led.toggle()
            gc.collect()


def main():
    cam = camlib.Camera(FRAMESIZE)
    errs = cam.lock() if LOCK_CAMERA else []
    exp, gain, wb = cam.state()
    cam_info = {"locked": LOCK_CAMERA, "exp_us": exp, "gain_db": gain,
                "wb": list(wb) if wb else None, "lock_errors": errs}
    tof = camlib.open_tof()
    ip = wifi_up()
    led.set(True)

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(socket.getaddrinfo("0.0.0.0", PORT)[0][-1])
    srv.listen(1)
    while True:
        print("# stream_server ready: %s:%d  camera=%s" % (ip, PORT, cam_info))
        client, addr = srv.accept()
        print("# client", addr)
        try:
            serve(client, cam, tof, cam_info)
        except OSError as e:
            print("# client gone:", e)
        except Exception as e:          # keep the server alive on unexpected bugs
            print("# error:", e)
        finally:
            vehicle_stop()        # safety: never keep driving without a viewer
            try:
                client.close()
            except Exception:
                pass


main()
