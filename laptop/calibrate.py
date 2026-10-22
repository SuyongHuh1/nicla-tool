"""Phase 1-2: camera geometry on the floor.

Subcommands
  board       print-ready chessboard PNG (A4, 300 dpi)
                py laptop\\calibrate.py board --cols 9 --rows 7 --square-mm 20
  intrinsics  lens calibration from 10-20 photos of the board at different poses (optional)
                py laptop\\calibrate.py intrinsics captures\\cal_*.jpg
  floor       board lying flat on the floor in the mounted camera view
                py laptop\\calibrate.py floor captures\\floor_h65_t45.jpg [--intrinsics results\\calib\\intrinsics.json]

`floor` computes the image->floor homography and reports mm per pixel, the
visible floor area and the FOMO cell size on the floor (96x96 input, 8 px cells).
Photos come from laptop/viewer.py ('c' key saves the raw frame to captures/).
"""
import argparse
import glob
import json
import math
import os
import sys

import cv2
import numpy as np

FOMO_INPUT = 96
FOMO_STRIDE = 8


# ------------------------------------------------------------------ board
def make_board(cols, rows, square_mm, dpi=300, page_mm=(297, 210)):
    """Landscape A4 chessboard with a 50 mm scale bar to check print scaling."""
    px_per_mm = dpi / 25.4
    W, H = int(page_mm[0] * px_per_mm), int(page_mm[1] * px_per_mm)
    img = np.full((H, W), 255, np.uint8)
    bw, bh = cols * square_mm, rows * square_mm
    if bw > page_mm[0] - 20 or bh > page_mm[1] - 30:
        raise ValueError("board %dx%d mm does not fit on A4 with margins" % (bw, bh))
    ox, oy = (page_mm[0] - bw) / 2, (page_mm[1] - bh) / 2 - 5
    for r in range(rows):
        for c in range(cols):
            if (r + c) % 2 == 0:
                x0, y0 = int((ox + c * square_mm) * px_per_mm), int((oy + r * square_mm) * px_per_mm)
                x1, y1 = int((ox + (c + 1) * square_mm) * px_per_mm), int((oy + (r + 1) * square_mm) * px_per_mm)
                img[y0:y1, x0:x1] = 0
    yb = int((oy + bh + 8) * px_per_mm)
    xb = int(ox * px_per_mm)
    cv2.rectangle(img, (xb, yb), (xb + int(50 * px_per_mm), yb + int(2 * px_per_mm)), 0, -1)
    cv2.putText(img, "50 mm (check with a ruler)   %dx%d squares, %g mm, inner corners %dx%d" %
                (cols, rows, square_mm, cols - 1, rows - 1),
                (xb, yb + int(9 * px_per_mm)), cv2.FONT_HERSHEY_SIMPLEX, 1.6, 0, 3)
    return img


# ------------------------------------------------------------- detection
def find_corners(gray, pattern):
    flags = cv2.CALIB_CB_ADAPTIVE_THRESH | cv2.CALIB_CB_NORMALIZE_IMAGE
    ok, corners = cv2.findChessboardCorners(gray, pattern, flags)
    if not ok:
        return None
    crit = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.01)
    return cv2.cornerSubPix(gray, corners, (5, 5), (-1, -1), crit)


def object_points(pattern, square_mm):
    cols, rows = pattern
    g = np.zeros((rows * cols, 3), np.float32)
    g[:, :2] = np.mgrid[0:cols, 0:rows].T.reshape(-1, 2) * square_mm
    return g


def load_gray(path):
    img = cv2.imread(path)
    if img is None:
        raise FileNotFoundError(path)
    return img, cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)


# ------------------------------------------------------------ intrinsics
def calib_intrinsics(paths, pattern, square_mm):
    objp = object_points(pattern, square_mm)
    objs, imgs, size, used = [], [], None, []
    for p in paths:
        _, g = load_gray(p)
        size = g.shape[::-1]
        c = find_corners(g, pattern)
        if c is not None:
            objs.append(objp)
            imgs.append(c)
            used.append(os.path.basename(p))
    if len(objs) < 5:
        raise RuntimeError("board found in only %d images (need >= 5)" % len(objs))
    rms, K, dist, _, _ = cv2.calibrateCamera(objs, imgs, size, None, None)
    return {"rms_px": float(rms), "K": K.tolist(), "dist": dist.ravel().tolist(), "size": list(size), "images": used}


# ----------------------------------------------------------------- floor
def floor_homography(img_pts, pattern, square_mm):
    obj = object_points(pattern, square_mm)[:, :2]
    H, _ = cv2.findHomography(img_pts.reshape(-1, 2), obj, 0)
    return H


def apply_h(H, pts):
    pts = np.asarray(pts, np.float64).reshape(-1, 2)
    p = np.hstack([pts, np.ones((len(pts), 1))]) @ H.T
    return p[:, :2] / p[:, 2:3], p[:, 2]


def local_scale(H, x, y):
    """mm per pixel at (x, y): average of the x and y step lengths on the floor."""
    q, _ = apply_h(H, [(x, y), (x + 1, y), (x, y + 1)])
    return float((np.linalg.norm(q[1] - q[0]) + np.linalg.norm(q[2] - q[0])) / 2), q[0]


def floor_report(H, w, h):
    rep = {}
    for name, (x, y) in {"center": (w / 2, h / 2), "bottom_center": (w / 2, h - 1), "top_center": (w / 2, 0)}.items():
        _, wsign = apply_h(H, [(x, y)])
        if wsign[0] * apply_h(H, [(w / 2, h - 1)])[1][0] <= 0:
            rep[name] = None   # above the horizon
            continue
        s, _ = local_scale(H, x, y)
        rep[name] = s
    corners = [(0, h - 1), (w - 1, h - 1), (w - 1, 0), (0, 0)]
    q, ws = apply_h(H, corners)
    ref = ws[0]
    if all(wi * ref > 0 for wi in ws):
        quad = q
    else:
        quad = None
    rep["footprint_mm2"] = float(cv2.contourArea(quad.astype(np.float32))) if quad is not None else None
    rep["footprint_quad_mm"] = quad.tolist() if quad is not None else None
    if quad is not None:
        rep["near_width_mm"] = float(np.linalg.norm(quad[1] - quad[0]))
        rep["far_width_mm"] = float(np.linalg.norm(quad[2] - quad[3]))
        rep["depth_mm"] = float(np.linalg.norm((quad[0] + quad[1]) / 2 - (quad[2] + quad[3]) / 2))
    cell_px = FOMO_STRIDE * min(w, h) / FOMO_INPUT    # centre-square crop resized to 96x96
    rep["fomo_cell_px"] = cell_px
    rep["fomo_cell_mm_center"] = rep["center"] * cell_px if rep["center"] else None
    return rep


def draw_floor_grid(img, H, step_mm=10, extent_mm=300):
    """Project a 10 mm floor grid back into the image as a visual check."""
    Hinv = np.linalg.inv(H)
    out = img.copy()
    for v in np.arange(-extent_mm, extent_mm + 1, step_mm):
        for a, b in (((v, -extent_mm), (v, extent_mm)), ((-extent_mm, v), (extent_mm, v))):
            seg = np.linspace(a, b, 60)
            p, ws = apply_h(Hinv, seg)
            ok = ws > 0 if ws.mean() > 0 else ws < 0
            p = p[ok]
            if len(p) > 1:
                color = (0, 200, 255) if v % 50 == 0 else (0, 255, 0)
                cv2.polylines(out, [p.astype(np.int32)], False, color, 1, cv2.LINE_AA)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("board", "intrinsics", "floor"):
        s = sub.add_parser(name)
        s.add_argument("--cols", type=int, default=9, help="squares across")
        s.add_argument("--rows", type=int, default=7, help="squares down")
        s.add_argument("--square-mm", type=float, default=20.0)
        s.add_argument("--out", default=os.path.join("results", "calib"))
        if name in ("intrinsics", "floor"):
            s.add_argument("images", nargs="+")
        if name == "floor":
            s.add_argument("--intrinsics", help="intrinsics.json from the intrinsics step")
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    pattern = (a.cols - 1, a.rows - 1)   # inner corners

    if a.cmd == "board":
        img = make_board(a.cols, a.rows, a.square_mm)
        p = os.path.join(a.out, "chessboard_%dx%d_%gmm.png" % (a.cols, a.rows, a.square_mm))
        cv2.imwrite(p, img)
        # PDF with the exact A4 page size, so "actual size" printing keeps the scale
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig = plt.figure(figsize=(297 / 25.4, 210 / 25.4))
        ax = fig.add_axes([0, 0, 1, 1])
        ax.imshow(img, cmap="gray", vmin=0, vmax=255, interpolation="nearest")
        ax.axis("off")
        pdf = os.path.splitext(p)[0] + ".pdf"
        fig.savefig(pdf)
        plt.close(fig)
        print("-> %s\n-> %s  (print the PDF at 100%% / actual size, then check the 50 mm bar)" % (p, pdf))
        return 0

    paths = [p for pat in a.images for p in (glob.glob(pat) or [pat])]
    if a.cmd == "intrinsics":
        res = calib_intrinsics(paths, pattern, a.square_mm)
        p = os.path.join(a.out, "intrinsics.json")
        with open(p, "w") as f:
            json.dump(res, f, indent=2)
        print("rms reprojection error %.3f px from %d images -> %s" % (res["rms_px"], len(res["images"]), p))
        return 0

    # floor
    img, gray = load_gray(paths[0])
    h, w = gray.shape
    corners = find_corners(gray, pattern)
    if corners is None:
        sys.exit("chessboard (%dx%d inner corners) not found in %s" % (pattern[0], pattern[1], paths[0]))
    pts = corners.reshape(-1, 2)
    if a.intrinsics:
        with open(a.intrinsics) as f:
            intr = json.load(f)
        K, dist = np.array(intr["K"]), np.array(intr["dist"])
        pts = cv2.undistortPoints(pts.reshape(-1, 1, 2), K, dist, P=K).reshape(-1, 2)
    H = floor_homography(pts, pattern, a.square_mm)
    obj = object_points(pattern, a.square_mm)[:, :2]
    proj, _ = apply_h(H, pts)
    resid = float(np.sqrt(np.mean(np.sum((proj - obj) ** 2, axis=1))))
    rep = floor_report(H, w, h)
    rep.update({"image": os.path.basename(paths[0]), "size": [w, h], "H_img_to_floor_mm": H.tolist(),
                "fit_rms_mm": resid, "undistorted": bool(a.intrinsics)})
    stem = os.path.splitext(os.path.basename(paths[0]))[0]
    with open(os.path.join(a.out, "floor_%s.json" % stem), "w") as f:
        json.dump(rep, f, indent=2)
    vis = draw_floor_grid(img, H)
    cv2.drawChessboardCorners(vis, pattern, corners, True)
    cv2.imwrite(os.path.join(a.out, "floor_%s_check.png" % stem), vis)

    def f(v, fmt="%.3f"):
        return fmt % v if v is not None else "-"
    print("image %dx%d, fit residual %.2f mm" % (w, h, resid))
    print("mm/px  bottom %s | center %s | top %s" % (f(rep["bottom_center"]), f(rep["center"]), f(rep["top_center"])))
    if rep["footprint_quad_mm"]:
        print("visible floor: near width %.0f mm, far width %.0f mm, depth %.0f mm" %
              (rep["near_width_mm"], rep["far_width_mm"], rep["depth_mm"]))
    else:
        print("visible floor: image reaches above the horizon (only the lower part is floor)")
    print("FOMO cell = %.1f px = %s mm at image centre" % (rep["fomo_cell_px"], f(rep["fomo_cell_mm_center"], "%.1f")))
    print("-> %s" % os.path.join(a.out, "floor_%s.json" % stem))
    return 0


if __name__ == "__main__":
    sys.exit(main())
