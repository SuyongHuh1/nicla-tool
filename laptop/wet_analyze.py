"""Phase 1-6: can the camera see a liquid puddle, and which cue shows it best?

Input: a viewer recording made with the illumination LED alternating
(viewer.py --illum alt --record), camera and puddle not moving.
You mark the puddle (wet) and a patch of clean floor (dry) once:
  py laptop\\wet_analyze.py recordings\\20261023_101500_wood_water --select
which prints the --wet/--dry values to reuse, e.g.
  py laptop\\wet_analyze.py recordings\\... --wet 40,176,60,28 --dry 200,190,60,30

Cues compared (d' = separation from dry floor, >= 3 means clearly visible)
  plain_L   brightness, LED off          (what an ordinary camera sees)
  plain_b   yellowness (b*), LED off     (urine colour)
  lit_L     brightness, LED on, p90      (single lit frame)
  diff      LED on - off, p90            (our LED's glint only)
  ndiff     diff / local median, p90     (robust to an uneven LED spot)
coverage = share of puddle pixels above the dry floor's 99th percentile (diff).

Outputs: results/wet/<label>.json, <label>.png (off | on | diff), summary.md
"""
import argparse
import glob
import json
import os
import sys

import cv2
import numpy as np

import wetlib

CUES = ("plain_L", "plain_b", "lit_L", "diff", "ndiff")
LABELS_KO = {"plain_L": "밝기(LED 끔)", "plain_b": "노란색(LED 끔)", "lit_L": "밝기(LED 켬)",
             "diff": "켬−끔 차분", "ndiff": "정규화 차분"}


def parse_rect(s):
    v = [int(x) for x in s.split(",")]
    if len(v) != 4:
        raise argparse.ArgumentTypeError("x,y,w,h")
    return tuple(v)


def load_recording(d):
    recs = []
    with open(os.path.join(d, "meta.jsonl"), encoding="utf-8") as f:
        for ln in f:
            r = json.loads(ln)
            if "led" in r["hdr"]:
                recs.append(r)
    recs.sort(key=lambda r: r["hdr"]["seq"])
    return recs


def read_img(d, r):
    return cv2.imread(os.path.join(d, "frames", r["file"]), cv2.IMREAD_COLOR)


def make_pairs(recs):
    pairs = []
    i = 0
    while i + 1 < len(recs):
        a, b = recs[i], recs[i + 1]
        if b["hdr"]["seq"] - a["hdr"]["seq"] == 1 and a["hdr"]["led"] != b["hdr"]["led"]:
            on, off = (a, b) if a["hdr"]["led"] else (b, a)
            pairs.append((on, off))
            i += 2
        else:
            i += 1
    return pairs


def analyse(d, wet, dry, max_pairs=60):
    recs = load_recording(d)
    pairs = make_pairs(recs)
    if not pairs:
        raise RuntimeError("no LED on/off pairs - record with: viewer.py --illum alt --record")
    step = max(1, len(pairs) // max_pairs)
    pairs = pairs[::step][:max_pairs]
    scores = {c: [] for c in CUES}
    cov, on_means, off_means = [], [], []
    last = None
    for on_r, off_r in pairs:
        on, off = read_img(d, on_r), read_img(d, off_r)
        if on is None or off is None:
            continue
        lon, loff = wetlib.lab(on), wetlib.lab(off)
        on_means.append(float(wetlib.roi(lon[..., 0], dry).mean()))
        off_means.append(float(wetlib.roi(loff[..., 0], dry).mean()))
        dm = wetlib.diff_map(on, off)
        nd = wetlib.normalised_diff(on, off)
        chans = {"plain_L": (loff[..., 0], "mean"), "plain_b": (loff[..., 2], "mean"),
                 "lit_L": (lon[..., 0], "p90"), "diff": (dm, "p90"), "ndiff": (nd, "p90")}
        for c, (a, stat) in chans.items():
            scores[c].append(wetlib.separation(wetlib.roi(a, wet), wetlib.roi(a, dry), stat))
        cov.append(wetlib.coverage(wetlib.roi(dm, wet), wetlib.roi(dm, dry)))
        last = (on, off, dm)
    led_gain = float(np.mean(on_means) - np.mean(off_means))
    res = {"recording": os.path.basename(os.path.normpath(d)), "pairs": len(cov), "wet": list(wet), "dry": list(dry),
           "led_gain_L": round(led_gain, 2),
           "dprime": {c: round(float(np.median(v)), 2) for c, v in scores.items()},
           "coverage": round(float(np.median(cov)), 3)}
    best = max(CUES, key=lambda c: res["dprime"][c])
    res["best_cue"] = best
    res["verdict"] = "VISIBLE" if res["dprime"][best] >= 3 else ("WEAK" if res["dprime"][best] >= 1.5 else "NOT_VISIBLE")
    warn = []
    if led_gain < 0:
        warn.append("LED-on frames are darker than LED-off: frames are labelled one frame late -> raise 'settle' (viewer key, or ILLUM_SETTLE)")
    elif led_gain < 3:
        warn.append("LED barely changes the image (gain %.1f L): LED too weak / pointed away, or ambient light too strong" % led_gain)
    res["warnings"] = warn
    return res, last


def panel(last, wet, dry):
    on, off, dm = last
    hm = wetlib.heatmap(dm)
    tiles = []
    for img, title in ((off, "LED off"), (on, "LED on"), (hm, "on - off")):
        t = img.copy()
        for r, c in ((wet, (0, 255, 255)), (dry, (255, 255, 0))):
            x, y, w, h = r
            cv2.rectangle(t, (x, y), (x + w, y + h), c, 1)
        cv2.putText(t, title, (6, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
        tiles.append(t)
    return np.hstack(tiles)


def write_summary(outdir):
    rows = []
    for p in sorted(glob.glob(os.path.join(outdir, "*.json"))):
        with open(p, encoding="utf-8") as f:
            rows.append((os.path.splitext(os.path.basename(p))[0], json.load(f)))
    lines = ["# 1-6 젖은 바닥(오줌) 가시성", "",
             "d' ≥ 3 이면 뚜렷하게 구분됨. 커버리지 = 웅덩이 픽셀 중 차분 영상에서 드러난 비율.", "",
             "| 조건 | " + " | ".join(LABELS_KO[c] for c in CUES) + " | 커버리지 | 최선 단서 | 판정 |",
             "|---|" + "---|" * (len(CUES) + 3)]
    for name, r in rows:
        lines.append("| %s | %s | %.0f%% | %s | %s |" % (name, " | ".join("%.1f" % r["dprime"][c] for c in CUES),
                                                       100 * r["coverage"], LABELS_KO[r["best_cue"]], r["verdict"]))
    warns = [(n, w) for n, r in rows for w in r.get("warnings", [])]
    if warns:
        lines += ["", "**주의**"] + ["- %s: %s" % (n, w) for n, w in warns]
    with open(os.path.join(outdir, "summary.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def select_rois(d):
    recs = load_recording(d)
    pairs = make_pairs(recs)
    if not pairs:
        sys.exit("no LED on/off pairs in %s" % d)
    on = read_img(d, pairs[len(pairs) // 2][0])
    off = read_img(d, pairs[len(pairs) // 2][1])
    view = np.hstack([on, wetlib.heatmap(wetlib.diff_map(on, off))])
    big = cv2.resize(view, None, fx=2, fy=2, interpolation=cv2.INTER_NEAREST)
    print("drag a box around the PUDDLE (left image), Enter to confirm")
    w = [int(v / 2) for v in cv2.selectROI("wet: puddle", big, False)]
    cv2.destroyAllWindows()
    print("now a box on CLEAN FLOOR nearby, Enter to confirm")
    dr = [int(v / 2) for v in cv2.selectROI("dry: clean floor", big, False)]
    cv2.destroyAllWindows()
    return tuple(w), tuple(dr)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("recording")
    ap.add_argument("--wet", type=parse_rect, help="puddle box x,y,w,h (image pixels)")
    ap.add_argument("--dry", type=parse_rect, help="clean floor box x,y,w,h")
    ap.add_argument("--select", action="store_true", help="draw the two boxes with the mouse")
    ap.add_argument("--label", help="result name (default: recording folder name)")
    ap.add_argument("--out", default=os.path.join("results", "wet"))
    a = ap.parse_args(argv)
    if a.select:
        a.wet, a.dry = select_rois(a.recording)
        print("reuse with: --wet %s --dry %s" % (",".join(map(str, a.wet)), ",".join(map(str, a.dry))))
    if not (a.wet and a.dry):
        ap.error("give --wet and --dry, or use --select")
    os.makedirs(a.out, exist_ok=True)
    label = a.label or os.path.basename(os.path.normpath(a.recording))
    res, last = analyse(a.recording, a.wet, a.dry)
    with open(os.path.join(a.out, label + ".json"), "w", encoding="utf-8") as f:
        json.dump(res, f, indent=2, ensure_ascii=False)
    cv2.imwrite(os.path.join(a.out, label + ".png"), panel(last, a.wet, a.dry))
    write_summary(a.out)
    print("%s: %d pairs, LED gain %.1f L" % (label, res["pairs"], res["led_gain_L"]))
    for c in CUES:
        print("  %-8s d' = %5.2f" % (c, res["dprime"][c]))
    print("  coverage %.0f%%  best=%s  -> %s" % (100 * res["coverage"], res["best_cue"], res["verdict"]))
    for w in res["warnings"]:
        print("  ! " + w)
    print("-> %s" % os.path.join(a.out, "summary.md"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
