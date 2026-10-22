"""Phase 1-3: can the VL53L1X tell 5 mm height steps apart?

Reads results/tof/*.csv written by capture.py. File names encode the condition:
    h<height_mm>_b<block_mm>[_<tag>].csv     e.g. h05_b30.csv, h10_b60_t45.csv
  height_mm : block height (h00 = bare floor, the baseline)
  block_mm  : block footprint size (30 / 60 mm)
  tag       : anything else (mount, tilt, ...) - files are grouped by (block, tag)

For every group the floor baseline d0 (h00) converts distance to height:
    h_est = (d0 - d) * sin(tilt)        tilt = ToF axis angle below horizontal
Separation of neighbouring heights is   d' = |mean_a - mean_b| / pooled_std
PASS: every neighbouring pair that is <= --step mm apart has d' >= --min-dprime.

Usage:  py laptop\\analyze_tof.py --tilt-deg 90
Outputs: results/tof/summary.csv, summary.png, verdict.md
"""
import argparse
import csv
import glob
import math
import os
import re
import sys

import numpy as np

LABEL_RE = re.compile(r"^h(\d+)_b(\d+)(?:_(.+))?$")
TOF_FOV_DEG = 27.0          # VL53L1X default full field of view
VALID_MAX_MM = 4000


def load(path):
    vals = []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            try:
                vals.append(float(row["distance_mm"]))
            except (KeyError, ValueError):
                vals.append(float("nan"))
    return np.array(vals, dtype=float)


def stats(d):
    valid = np.isfinite(d) & (d > 0) & (d < VALID_MAX_MM)
    v = d[valid]
    n = len(d)
    if len(v) == 0:
        return {"n": n, "valid_ratio": 0.0, "mean": float("nan"), "std": float("nan"), "median": float("nan"), "values": v}
    return {"n": n, "valid_ratio": len(v) / n if n else 0.0, "mean": float(v.mean()),
            "std": float(v.std(ddof=1)) if len(v) > 1 else 0.0, "median": float(np.median(v)), "values": v}


def dprime(a, b):
    pooled = math.sqrt((a["std"] ** 2 + b["std"] ** 2) / 2.0)
    diff = abs(a["mean"] - b["mean"])
    if pooled == 0:
        return float("inf") if diff > 0 else 0.0
    return diff / pooled


def footprint_mm(distance_mm, tilt_deg):
    """Approximate ToF spot on the floor: (across, along) diameters in mm."""
    across = 2.0 * distance_mm * math.tan(math.radians(TOF_FOV_DEG / 2.0))
    along = across / max(math.sin(math.radians(tilt_deg)), 1e-3)
    return across, along


def collect(indir):
    groups = {}
    skipped = []
    for p in sorted(glob.glob(os.path.join(indir, "*.csv"))):
        name = os.path.splitext(os.path.basename(p))[0]
        m = LABEL_RE.match(name)
        if not m:
            if name != "summary":
                skipped.append(name)
            continue
        h, b, tag = int(m.group(1)), int(m.group(2)), m.group(3) or ""
        groups.setdefault((b, tag), {})[h] = stats(load(p))
    return groups, skipped


def baseline_for(groups, key):
    b, tag = key
    if 0 in groups[key]:
        return groups[key][0]
    for (b2, t2), hs in groups.items():   # bare floor recorded once per tag is enough
        if t2 == tag and 0 in hs:
            return hs[0]
    return None


def analyse(groups, tilt_deg, step, min_dprime):
    sin_t = math.sin(math.radians(tilt_deg))
    report = []
    for key in sorted(groups):
        b, tag = key
        hs = groups[key]
        base = baseline_for(groups, key)
        rows = []
        for h in sorted(hs):
            s = hs[h]
            est = (base["mean"] - s["mean"]) * sin_t if base else float("nan")
            rows.append({"h": h, **{k: s[k] for k in ("n", "valid_ratio", "mean", "std", "median")},
                         "h_est": est, "err": est - h if base else float("nan")})
        pairs = []
        heights = sorted(hs)
        if base is not None and 0 not in hs:
            heights = [0] + heights
        series = {h: (hs[h] if h in hs else base) for h in heights}
        for h1, h2 in zip(heights, heights[1:]):
            dp = dprime(series[h1], series[h2])
            pairs.append({"h1": h1, "h2": h2, "dh": h2 - h1, "dprime": dp,
                          "monotonic": series[h2]["mean"] < series[h1]["mean"]})
        fine = [p for p in pairs if p["dh"] <= step]
        if not fine:
            verdict = "NO_DATA"
        elif all(p["dprime"] >= min_dprime and p["monotonic"] for p in fine):
            verdict = "PASS"
        else:
            verdict = "FAIL"
        fp = footprint_mm(base["mean"], tilt_deg) if base and math.isfinite(base["mean"]) else None
        errs = [abs(r["err"]) for r in rows if r["h"] > 0 and math.isfinite(r["err"])]
        report.append({"block": b, "tag": tag, "rows": rows, "pairs": pairs, "verdict": verdict,
                       "baseline_mm": base["mean"] if base else None, "footprint": fp,
                       "mae": float(np.mean(errs)) if errs else float("nan")})
    return report


def write_outputs(report, groups, outdir, tilt_deg, step, min_dprime):
    os.makedirs(outdir, exist_ok=True)
    with open(os.path.join(outdir, "summary.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["block_mm", "tag", "height_mm", "n", "valid_ratio", "mean_mm", "std_mm", "median_mm", "h_est_mm", "err_mm"])
        for g in report:
            for r in g["rows"]:
                w.writerow([g["block"], g["tag"], r["h"], r["n"], "%.3f" % r["valid_ratio"], "%.2f" % r["mean"],
                            "%.2f" % r["std"], "%.2f" % r["median"], "%.2f" % r["h_est"], "%.2f" % r["err"]])

    lines = ["# 1단계 ToF 판별력 판정", "",
             "- 기울기(tilt): %.0f° · 기준 간격: %d mm · 통과 기준 d' ≥ %.1f" % (tilt_deg, step, min_dprime), ""]
    overall = [g["verdict"] for g in report]
    if overall and all(v == "PASS" for v in overall):
        lines += ["**종합: PASS — ToF 높이 특징 채택**", ""]
    elif "PASS" in overall:
        lines += ["**종합: 조건부 — 일부 조건만 통과 (아래 표 참고)**", ""]
    else:
        lines += ["**종합: FAIL — 라인 레이저(삼각측량) 전환 검토**", ""]
    for g in report:
        title = "블록 %d mm%s" % (g["block"], (" · " + g["tag"]) if g["tag"] else "")
        lines += ["## %s → %s" % (title, g["verdict"]), ""]
        if g["footprint"]:
            a, b = g["footprint"]
            lines.append("- 바닥 기준거리 %.1f mm, ToF 측정 영역 약 %.0f × %.0f mm" % (g["baseline_mm"], a, b))
            if max(a, b) > g["block"]:
                lines.append("- ⚠ 측정 영역이 블록보다 큼 → 바닥 신호가 섞여 높이가 작게 나올 수 있음")
        else:
            lines.append("- ⚠ 바닥(h00) 측정 없음 → 높이 환산 불가")
        lines.append("- 높이 추정 평균 절대오차: %.1f mm" % g["mae"] if math.isfinite(g["mae"]) else "- 높이 추정 오차: -")
        lines += ["", "| 높이 | 유효율 | 평균 거리 | 표준편차 | 추정 높이 |", "|---|---|---|---|---|"]
        for r in g["rows"]:
            lines.append("| %d | %.0f%% | %.1f | %.2f | %.1f |" % (r["h"], 100 * r["valid_ratio"], r["mean"], r["std"], r["h_est"]))
        lines += ["", "| 비교 | d' | 단조감소 | 결과 |", "|---|---|---|---|"]
        for p in g["pairs"]:
            ok = p["dprime"] >= min_dprime and p["monotonic"]
            lines.append("| %d→%d mm | %.2f | %s | %s |" % (p["h1"], p["h2"], p["dprime"], "예" if p["monotonic"] else "아니오",
                                                          "통과" if ok else "미달"))
        lines.append("")
    with open(os.path.join(outdir, "verdict.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    sin_t = math.sin(math.radians(tilt_deg))
    n = len(report)
    fig, axes = plt.subplots(1, max(n, 1), figsize=(4.5 * max(n, 1), 4), squeeze=False)
    for ax, g in zip(axes[0], report):
        key = (g["block"], g["tag"])
        hs = sorted(groups[key])
        base = g["baseline_mm"]
        data = [((base - groups[key][h]["values"]) * sin_t) if base else groups[key][h]["values"] for h in hs]
        ax.boxplot(data, positions=hs, widths=2.5, manage_ticks=False)
        lim = max(hs) + 5 if hs else 10
        ax.plot([0, lim], [0, lim], "--", lw=1, color="gray", label="ideal")
        ax.set_xlim(-4, lim)
        ax.set_xticks(hs)
        ax.set_xlabel("true height (mm)")
        ax.set_ylabel("estimated height (mm)" if base else "distance (mm)")
        ax.set_title("block %d mm %s  [%s]" % (g["block"], g["tag"], g["verdict"]))
        ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(os.path.join(outdir, "summary.png"), dpi=120)
    plt.close(fig)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--in", dest="indir", default=os.path.join("results", "tof"))
    ap.add_argument("--out", dest="outdir")
    ap.add_argument("--tilt-deg", type=float, default=90.0, help="ToF axis angle below horizontal (90 = straight down)")
    ap.add_argument("--step", type=int, default=5, help="height step that must be resolvable (mm)")
    ap.add_argument("--min-dprime", type=float, default=3.0)
    a = ap.parse_args(argv)
    groups, skipped = collect(a.indir)
    if skipped:
        print("ignored (name not h<mm>_b<mm>[_tag]):", ", ".join(skipped))
    if not groups:
        sys.exit("no h*_b*.csv files in %s" % a.indir)
    report = analyse(groups, a.tilt_deg, a.step, a.min_dprime)
    write_outputs(report, groups, a.outdir or a.indir, a.tilt_deg, a.step, a.min_dprime)
    for g in report:
        print("block %3d mm %-10s %-8s  MAE %.1f mm" % (g["block"], g["tag"] or "-", g["verdict"], g["mae"]))
        for p in g["pairs"]:
            print("    %2d -> %2d mm  d'=%6.2f%s" % (p["h1"], p["h2"], p["dprime"], "" if p["monotonic"] else "  (not monotonic)"))
    print("-> %s" % os.path.join(a.outdir or a.indir, "verdict.md"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
