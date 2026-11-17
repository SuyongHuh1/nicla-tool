"""Summarize leave-one-group-out FOMO cross-validation folds.

The filename is retained for compatibility with the stool profile; the report
logic itself is class- and group-agnostic.
"""

import argparse
import json
from pathlib import Path

import numpy as np


METRICS = (
    "precision", "recall", "f1", "exact_count_rate",
    "top_within_one_cell_rate", "false_positives_per_image",
)


def load_folds(root):
    folds = []
    for validation_path in sorted(root.glob("fold_test_*/validation/validation_report.json")):
        validation = json.loads(validation_path.read_text(encoding="utf-8"))
        training_path = validation_path.parents[1] / "training_report.json"
        if not training_path.is_file():
            raise RuntimeError("training report missing: %s" % training_path)
        training = json.loads(training_path.read_text(encoding="utf-8"))
        groups = validation["split_integrity"].get(
            "groups", validation["split_integrity"]["shapes"])
        test_groups = groups["test"]
        val_groups = groups["validation"]
        if len(test_groups) != 1 or len(val_groups) != 1:
            raise RuntimeError("each fold must have one test and one validation group")
        roi_by_size = {item["roi_size"][0]: item
                       for item in validation["test_roi_sweep"]}
        folds.append({
            "test_group": test_groups[0],
            "validation_group": val_groups[0],
            "test_shape": test_groups[0],
            "validation_shape": val_groups[0],
            "group_field": validation["split_integrity"].get("group_field", "shape_id"),
            "class_name": validation.get("class_name", "object"),
            "status": validation["status"],
            "threshold": validation["selected_threshold"],
            "test": {key: validation["test"][key] for key in METRICS},
            "test_samples": validation["test"]["samples"],
            "model_bytes": training["tflite"]["bytes"],
            "epochs_completed": training["epochs_completed"],
            "roi_112_end_to_end_90": (
                roi_by_size.get(112, {}).get("bbox_coverage_at_least_90_all_gt_rate")),
            "roi_224_end_to_end_90": (
                roi_by_size.get(224, {}).get("bbox_coverage_at_least_90_all_gt_rate")),
            "report": validation_path.as_posix(),
        })
    if not folds:
        raise RuntimeError("no cross-validation fold reports found")
    test_groups = [fold["test_group"] for fold in folds]
    if len(test_groups) != len(set(test_groups)):
        raise RuntimeError("a group is used as test in more than one fold")
    return folds


def aggregate(folds):
    summary = {}
    for metric in METRICS:
        values = np.array([fold["test"][metric] for fold in folds], np.float64)
        summary[metric] = {
            "mean": float(values.mean()),
            "std": float(values.std()),
            "min": float(values.min()),
            "max": float(values.max()),
        }
    return summary


def make_markdown(report):
    lines = [
        "# Leave-one-group-out FOMO cross-validation",
        "",
        "Status: **%s**" % report["status"],
        "",
        "Each fold holds out one physical group for test, one different group",
        "for validation/threshold selection, and trains on the remainder.",
        "",
        "| Test | Validation | Samples | Threshold | Precision | Recall | F1 | Exact count | Center <=1 cell | ROI112 >=90% | ROI224 >=90% |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for fold in report["folds"]:
        metric = fold["test"]
        roi112 = fold["roi_112_end_to_end_90"]
        roi224 = fold["roi_224_end_to_end_90"]
        lines.append(
            "| {test} | {val} | {samples} | {threshold:.2f} | {precision:.1%} | "
            "{recall:.1%} | {f1:.1%} | {count:.1%} | {center:.1%} | {roi112} | {roi224} |".format(
                test=fold["test_group"], val=fold["validation_group"],
                samples=fold["test_samples"], threshold=fold["threshold"],
                precision=metric["precision"], recall=metric["recall"],
                f1=metric["f1"], count=metric["exact_count_rate"],
                center=metric["top_within_one_cell_rate"],
                roi112=("%.1f%%" % (roi112 * 100.0)) if roi112 is not None else "n/a",
                roi224=("%.1f%%" % (roi224 * 100.0)) if roi224 is not None else "n/a",
            ))
    mean = report["aggregate"]
    lines.extend([
        "",
        "## Across-fold result",
        "",
        "- F1: {mean:.1%} mean, {std:.1%} standard deviation, {worst:.1%} worst fold".format(
            mean=mean["f1"]["mean"], std=mean["f1"]["std"],
            worst=mean["f1"]["min"]),
        "- Recall: {mean:.1%} mean, {worst:.1%} worst fold".format(
            mean=mean["recall"]["mean"], worst=mean["recall"]["min"]),
        "- Center <=1 cell: {mean:.1%} mean, {worst:.1%} worst fold".format(
            mean=mean["top_within_one_cell_rate"]["mean"],
            worst=mean["top_within_one_cell_rate"]["min"]),
        "",
        "Cross-validation is used for model/threshold/ROI selection. After using",
        "these results, final accuracy must be measured once on a newly collected",
        "physical group that was not part of any fold.",
        "",
    ])
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    folds = load_folds(root)
    report = {
        "method": "leave-one-group-out with a separate validation group",
        "status": ("PROVISIONAL" if any(
            fold["status"] == "PROVISIONAL" for fold in folds) else "READY_FOR_NEW_FINAL_TEST"),
        "fold_count": len(folds),
        "folds": folds,
        "aggregate": aggregate(folds),
    }
    (root / "cv_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (root / "summary.md").write_text(make_markdown(report), encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        "fold_count": report["fold_count"],
        "mean_test_f1": report["aggregate"]["f1"]["mean"],
        "worst_test_f1": report["aggregate"]["f1"]["min"],
        "summary": (root / "summary.md").as_posix(),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
