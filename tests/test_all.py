import csv
import json
import os
import socket
import subprocess
import sys
import threading
import time

import cv2
import numpy as np
import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "laptop"))

import analyze_exposure  # noqa: E402
import analyze_tof  # noqa: E402
import calibrate  # noqa: E402
import capture  # noqa: E402
import fake_nicla  # noqa: E402
import nvlink  # noqa: E402
import viewer  # noqa: E402

PY = sys.executable


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


# ---------------------------------------------------------------- protocol
def test_message_roundtrip():
    a, b = socket.socketpair()
    hdr = {"seq": 3, "det": [{"cls": "blob", "bbox": [1, 2, 3, 4]}], "txt": "한글"}
    nvlink.send_message(a, hdr, b"\xff\xd8jpeg")
    h2, p2 = nvlink.read_message(b)
    assert h2 == hdr and p2 == b"\xff\xd8jpeg"


def test_bad_magic():
    a, b = socket.socketpair()
    a.sendall(b"XXXX" + b"\0" * 8)
    with pytest.raises(nvlink.ProtocolError):
        nvlink.read_message(b)


def test_line_reader_partial_and_garbage():
    r = nvlink.LineReader()
    data = nvlink.encode_cmd({"t": "ping", "seq": 1}) + b"not json\n" + b'{"t": "stop"'
    assert r.feed(data[:5]) == []
    out = r.feed(data[5:])
    assert out == [{"t": "ping", "seq": 1}, {"t": "_bad"}]
    assert r.feed(b"}\n") == [{"t": "stop"}]


# ----------------------------------------------------------------- capture
def test_capture_parse_and_run(tmp_path):
    lines = ["# hello\n", "T,1,150\n", "garbage\n", "T,2,nan\n", "E,1,2,3,4,5\n"] + ["T,%d,149\n" % i for i in range(3, 20)]
    out = tmp_path / "x.csv"
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        n = capture.run(iter(lines), w, "T", 2, n=5, skip=1, echo=False)
    assert n == 5
    rows = list(csv.reader(open(out)))
    assert rows[0] == ["2", "nan"]


# ------------------------------------------------------------- analyze_tof
def write_tof(d, label, mean, std, n=100, seed=0, invalid=0):
    rng = np.random.default_rng(seed)
    v = rng.normal(mean, std, n)
    with open(os.path.join(d, label + ".csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["board_ms", "distance_mm"])
        for i, x in enumerate(v):
            w.writerow([i * 50, "nan" if i < invalid else "%.0f" % x])


def test_tof_pass_and_fail(tmp_path):
    good, bad = tmp_path / "good", tmp_path / "bad"
    good.mkdir()
    bad.mkdir()
    for i, h in enumerate([0, 5, 10, 20, 30]):
        write_tof(good, "h%02d_b30" % h, 150 - h, 0.8, seed=i, invalid=3)
        write_tof(bad, "h%02d_b30" % h, 150 - h, 4.0, seed=i)
    rg = analyze_tof.analyse(analyze_tof.collect(str(good))[0], 90, 5, 3.0)
    rb = analyze_tof.analyse(analyze_tof.collect(str(bad))[0], 90, 5, 3.0)
    assert rg[0]["verdict"] == "PASS" and rg[0]["mae"] < 1.0
    assert rb[0]["verdict"] == "FAIL"
    assert analyze_tof.main(["--in", str(good)]) == 0
    assert "PASS" in open(good / "verdict.md", encoding="utf-8").read()
    assert (good / "summary.png").exists()


def test_tof_tilt_and_shared_baseline(tmp_path):
    # tilt 45 deg: distance changes by h / sin(45); baseline recorded once as h00_b00_t45
    s = np.sin(np.radians(45))
    write_tof(tmp_path, "h00_b00_t45", 200, 0.8)
    for h in (5, 10):
        write_tof(tmp_path, "h%02d_b60_t45" % h, 200 - h / s, 0.8, seed=h)
    rep = analyze_tof.analyse(analyze_tof.collect(str(tmp_path))[0], 45, 5, 3.0)
    g = [r for r in rep if r["block"] == 60][0]
    assert g["verdict"] == "PASS"
    assert abs(g["rows"][-1]["h_est"] - 10) < 1.0
    assert g["footprint"][1] > g["footprint"][0]   # elongated along the tilt


def test_exposure(tmp_path):
    with open(tmp_path / "lock.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["board_ms", "l_mean", "l_stdev", "exposure_us", "gain_db"])
        for i in range(1200):
            w.writerow([i * 500, 50 + (i % 3) * 0.5, 5, 12000, 6.0])
    with open(tmp_path / "auto.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["board_ms", "l_mean", "l_stdev", "exposure_us", "gain_db"])
        for i in range(1200):
            w.writerow([i * 500, 40 + i / 60, 5, 8000 + i, 6.0])
    assert analyze_exposure.main(["--in", str(tmp_path)]) == 0
    txt = open(tmp_path / "verdict.md", encoding="utf-8").read()
    assert "| lock |" in txt and "| auto |" in txt
    r = analyze_exposure.analyse_one(*analyze_exposure.load(str(tmp_path / "lock.csv")), 5.0)
    assert r["verdict"] == "PASS"
    r = analyze_exposure.analyse_one(*analyze_exposure.load(str(tmp_path / "auto.csv")), 5.0)
    assert r["verdict"] == "FAIL"


# --------------------------------------------------------------- calibrate
def test_floor_calibration_recovers_scale(tmp_path):
    board = calibrate.make_board(9, 7, 20, dpi=100)
    cv2.imwrite(str(tmp_path / "board.png"), board)
    # render the printed board as seen by a tilted camera: board mm -> image px
    px_per_mm = 100 / 25.4
    ys, xs = np.where(board < 128)
    ox_mm, oy_mm = xs.min() / px_per_mm, ys.min() / px_per_mm     # top-left of the squares
    page_corners_mm = np.float32([[ox_mm, oy_mm], [ox_mm + 180, oy_mm], [ox_mm + 180, oy_mm + 140], [ox_mm, oy_mm + 140]])
    img_corners = np.float32([[90, 70], [230, 70], [270, 200], [50, 200]])     # trapezoid = perspective
    Hm = cv2.getPerspectiveTransform(page_corners_mm * px_per_mm, img_corners)
    view = cv2.warpPerspective(board, Hm, (320, 240), borderValue=200)
    view = cv2.GaussianBlur(cv2.cvtColor(view, cv2.COLOR_GRAY2BGR), (3, 3), 0)
    p = tmp_path / "floor.jpg"
    cv2.imwrite(str(p), view)
    out = tmp_path / "calib"
    assert calibrate.main(["floor", str(p), "--out", str(out)]) == 0
    rep = json.load(open(out / "floor_floor.json"))
    assert rep["fit_rms_mm"] < 1.0
    # near (bottom) edge of the board: 180 mm over 220 px; far edge 180 mm over 140 px
    # scale grows toward the far (top) side; the board's near edge is 180 mm / 220 px = 0.82 mm/px
    assert 0.5 < rep["bottom_center"] < rep["center"] < rep["top_center"]
    assert 0.8 < rep["center"] < 1.3
    assert rep["fomo_cell_px"] == pytest.approx(20.0)
    assert (out / "floor_floor_check.png").exists()


def test_make_board_rejects_too_big():
    with pytest.raises(ValueError):
        calibrate.make_board(15, 11, 25)


# --------------------------------------------------------- viewer overlay
def test_draw_overlay_all_fields():
    img = np.zeros((480, 640, 3), np.uint8)
    hdr = {"det": [{"cls": "blob", "bbox": [10, 10, 40, 30], "cx": 30, "cy": 25, "px": 900},
                   {"grade": 3, "conf": 0.9, "cx": 100, "cy": 100, "contour": [[90, 90], [110, 90], [110, 110]],
                    "area_mm2": 1200.0, "height_mm": 8.0}]}
    viewer.draw_overlay(img, hdr, 2.0)
    assert img.sum() > 0


# ------------------------------------------------- end to end (simulated)
def run_viewer_headless(port, tmp_path, seconds=3.0, extra=()):
    r = subprocess.run([PY, os.path.join(ROOT, "laptop", "viewer.py"), "--host", "127.0.0.1", "--port", str(port),
                        "--headless", "--duration", str(seconds), "--label", "t", "--out", str(tmp_path / "res"),
                        "--jpeg-q", "30", *extra], cwd=tmp_path, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
    return json.load(open(tmp_path / "res" / "stream" / "t.json"))


def test_viewer_with_fake_board(tmp_path):
    stop = threading.Event()
    ready = []
    port = free_port()
    th = threading.Thread(target=fake_nicla.run_server, args=("127.0.0.1", port, 20.0, stop, ready), daemon=True)
    th.start()
    for _ in range(50):
        if ready:
            break
        time.sleep(0.05)
    try:
        s = run_viewer_headless(port, tmp_path, extra=("--record",))
    finally:
        stop.set()
    assert s["fps"] > 10
    assert s["rtt_samples"] >= 2 and s["latency_ms_p50"] is not None
    assert 30 in s["jpeg_q"]
    rec = [d for d in os.listdir(tmp_path / "recordings")]
    assert len(rec) == 1
    meta = open(tmp_path / "recordings" / rec[0] / "meta.jsonl").read().splitlines()
    assert len(meta) > 20 and "hdr" in json.loads(meta[0])


def test_board_stream_server_under_shim(tmp_path):
    """Runs the real nicla/stream_server.py with fake board modules."""
    port = free_port()
    proc = subprocess.Popen([PY, os.path.join(ROOT, "tests", "run_board_script.py"),
                             os.path.join(ROOT, "nicla", "stream_server.py"), str(port)],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        sock = None
        for _ in range(100):
            try:
                sock = nvlink.connect("127.0.0.1", port, timeout=2)
                break
            except OSError:
                time.sleep(0.1)
        assert sock is not None, "board sim did not start"
        sock.sendall(nvlink.encode_cmd({"t": "ping", "seq": 7}) + nvlink.encode_cmd({"t": "drive", "l": 150, "r": -20, "seq": 8})
                     + nvlink.encode_cmd({"t": "set", "key": "jpeg_q", "val": 20, "seq": 9}))
        got_pong = False
        hdrs = []
        for _ in range(15):
            h, jpg = nvlink.read_message(sock)
            hdrs.append(h)
            assert cv2.imdecode(np.frombuffer(jpg, np.uint8), cv2.IMREAD_COLOR).shape == (240, 320, 3)
            got_pong |= h.get("pong", {}).get("seq") == 7
        assert got_pong
        last = hdrs[-1]
        assert last["drive"] == [100, -20]          # clamped
        assert last["q"] == 20 and last["tof_mm"] is not None
        assert any(h["det"] for h in hdrs)
        assert "cam" in hdrs[0] and hdrs[0]["cam"]["locked"]
        sock.close()
    finally:
        proc.kill()
        out = proc.communicate()[0]
    assert "Traceback" not in out, out


@pytest.mark.parametrize("script,prefix,ncols", [("tof_logger.py", "T", 2), ("exposure_test.py", "E", 5)])
def test_board_loggers_match_capture(script, prefix, ncols):
    proc = subprocess.Popen([PY, os.path.join(ROOT, "tests", "run_board_script.py"), os.path.join(ROOT, "nicla", script)],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        time.sleep(2.5)
    finally:
        proc.kill()
    out = proc.communicate()[0]
    assert "Traceback" not in out, out
    rows = [capture.parse_line(ln, prefix, ncols) for ln in out.splitlines()]
    rows = [r for r in rows if r]
    assert len(rows) >= 3, out
