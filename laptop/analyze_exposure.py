"""Phase 1-4: is image brightness stable with the camera locked?

Reads results/exposure/*.csv (capture.py --kind exposure). For each file:
  drift %  = (max - min) of centre L_mean / its average * 100
  slope    = linear trend of L_mean per minute
  exposure = whether exposure_us stayed constant (lock really held)
PASS: drift <= --max-drift-pct and exposure constant.

Usage:  py laptop\\analyze_exposure.py
Outputs: results/exposure/summary.png, verdict.md
"""
import argparse
import csv
import glob
import os
import sys

import numpy as np


def load(path):
    t, l, e = [], [], []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            try:
                t.append(float(row["board_ms"]))
                l.append(float(row["l_mean"]))
                e.append(float(row["exposure_us"]))
            except (KeyError, ValueError):
                continue
    return np.array(t), np.array(l), np.array(e)


def analyse_one(t, l, e, max_drift):
    if len(l) < 2:
        return None
    mins = (t - t[0]) / 60000.0
    drift = (l.max() - l.min()) / max(l.mean(), 1e-6) * 100.0
    slope = float(np.polyfit(mins, l, 1)[0]) if mins[-1] > 0 else 0.0
    ef = e[np.isfinite(e)]
    exp_const = bool(len(ef) == 0 or ef.max() - ef.min() <= 1)
    return {"minutes": float(mins[-1]), "mean": float(l.mean()), "drift_pct": float(drift), "slope": slope,
            "exp_const": exp_const, "exp_known": len(ef) > 0,
            "verdict": "PASS" if drift <= max_drift and exp_const else "FAIL", "mins": mins, "l": l}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--in", dest="indir", default=os.path.join("results", "exposure"))
    ap.add_argument("--max-drift-pct", type=float, default=5.0)
    a = ap.parse_args(argv)
    res = {}
    for p in sorted(glob.glob(os.path.join(a.indir, "*.csv"))):
        r = analyse_one(*load(p), a.max_drift_pct)
        if r:
            res[os.path.splitext(os.path.basename(p))[0]] = r
    if not res:
        sys.exit("no csv files in %s" % a.indir)

    lines = ["# 1단계 조명·노출 고정 판정", "", "- 기준: 밝기 변동 ≤ %.1f%%, 노출값 고정 유지" % a.max_drift_pct, "",
             "| 조건 | 시간(분) | 평균 L | 변동 | 추세(L/분) | 노출 고정 | 결과 |", "|---|---|---|---|---|---|---|"]
    for k, r in res.items():
        ec = ("예" if r["exp_const"] else "아니오") if r["exp_known"] else "확인 불가"
        lines.append("| %s | %.1f | %.1f | %.2f%% | %+.3f | %s | %s |" % (k, r["minutes"], r["mean"], r["drift_pct"], r["slope"], ec, r["verdict"]))
        print("%-24s %5.1f min  drift %5.2f%%  slope %+.3f/min  exp_const=%s  %s" % (k, r["minutes"], r["drift_pct"], r["slope"], r["exp_const"], r["verdict"]))
    with open(os.path.join(a.indir, "verdict.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(8, 4))
    for k, r in res.items():
        ax.plot(r["mins"], r["l"], label="%s (%.1f%%)" % (k, r["drift_pct"]))
    ax.set_xlabel("minutes")
    ax.set_ylabel("centre L mean")
    ax.grid(alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(os.path.join(a.indir, "summary.png"), dpi=120)
    plt.close(fig)
    print("-> %s" % os.path.join(a.indir, "verdict.md"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
