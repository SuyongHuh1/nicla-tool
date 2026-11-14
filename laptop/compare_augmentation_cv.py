"""Compare completed FOMO augmentation cross-validation runs.

The selector treats mean F1 scores within ``--f1-tolerance`` as effectively
tied.  It then prefers worst-fold F1, exact instance count, localization, and
lower false-positive rate in that order.  This keeps a tiny random F1 change
from overriding behavior that matters to the downstream robot ROI.
"""

import argparse
import json
from pathlib import Path


DISPLAY_METRICS = (
    "precision",
    "recall",
    "f1",
    "exact_count_rate",
    "top_within_one_cell_rate",
    "false_positives_per_image",
)


def load_runs(root, names):
    runs = []
    for name in names:
        path = root / name / "cv_report.json"
        if not path.is_file():
            raise RuntimeError("cross-validation report missing: %s" % path)
        report = json.loads(path.read_text(encoding="utf-8"))
        runs.append({
            "name": name,
            "report": path.as_posix(),
            "fold_count": report["fold_count"],
            "aggregate": report["aggregate"],
        })
    return runs


def select_run(runs, f1_tolerance):
    best_mean_f1 = max(run["aggregate"]["f1"]["mean"] for run in runs)
    candidates = [
        run for run in runs
        if best_mean_f1 - run["aggregate"]["f1"]["mean"] <= f1_tolerance
    ]

    def ranking(run):
        aggregate = run["aggregate"]
        return (
            aggregate["f1"]["min"],
            aggregate["exact_count_rate"]["mean"],
            aggregate["top_within_one_cell_rate"]["mean"],
            -aggregate["false_positives_per_image"]["mean"],
            aggregate["precision"]["mean"],
            aggregate["recall"]["mean"],
        )

    return max(candidates, key=ranking), best_mean_f1, candidates


def make_markdown(report):
    lines = [
        "# FOMO augmentation comparison",
        "",
        "All runs use the same reviewed labels, group folds, seed, tiny FOMO",
        "architecture, and 30-epoch training budget.",
        "",
        "| Augmentation | Mean F1 | Worst F1 | Precision | Recall | Exact count | Center <=1 cell | FP/image |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for run in report["runs"]:
        aggregate = run["aggregate"]
        lines.append(
            "| {name} | {f1:.2%} | {worst:.2%} | {precision:.2%} | "
            "{recall:.2%} | {count:.2%} | {center:.2%} | {fp:.3f} |".format(
                name=run["name"],
                f1=aggregate["f1"]["mean"],
                worst=aggregate["f1"]["min"],
                precision=aggregate["precision"]["mean"],
                recall=aggregate["recall"]["mean"],
                count=aggregate["exact_count_rate"]["mean"],
                center=aggregate["top_within_one_cell_rate"]["mean"],
                fp=aggregate["false_positives_per_image"]["mean"],
            )
        )
    lines.extend([
        "",
        "Selected: **%s**" % report["selected"],
        "",
        "Mean F1 values within %.2f percentage points are treated as tied. "
        "The tie-break order is worst-fold F1, exact count, localization, "
        "false positives, precision, then recall." % (report["f1_tolerance"] * 100.0),
        "",
    ])
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root")
    parser.add_argument("--runs", default="none,mild,default")
    parser.add_argument("--f1-tolerance", type=float, default=0.005)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    names = [item.strip() for item in args.runs.split(",") if item.strip()]
    runs = load_runs(root, names)
    selected, best_mean_f1, candidates = select_run(runs, args.f1_tolerance)
    report = {
        "method": "matched leave-one-group-out cross-validation",
        "selection_rule": (
            "within f1 tolerance: worst F1, exact count, localization, "
            "negative FP/image, precision, recall"
        ),
        "f1_tolerance": args.f1_tolerance,
        "best_mean_f1": best_mean_f1,
        "tied_candidates": [run["name"] for run in candidates],
        "selected": selected["name"],
        "runs": runs,
    }
    (root / "comparison.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (root / "comparison.md").write_text(make_markdown(report), encoding="utf-8")
    print(json.dumps({
        "selected": report["selected"],
        "tied_candidates": report["tied_candidates"],
        "comparison": (root / "comparison.md").as_posix(),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
