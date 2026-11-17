"""Score an untouched FOMO inference report against reviewed GT boxes.

Ground-truth boxes come from the human-reviewed metadata.  FOMO detections
are point/ROI predictions, so matching is one-to-one by detector center: a
center must be inside a padded GT box or close to that box's center.
"""

import argparse
import json
import math
from pathlib import Path


FINAL_STATUSES = {"accepted", "corrected"}


def read_jsonl(path):
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def load_ground_truth(session_dir):
    metadata_path = session_dir / "metadata.jsonl"
    if not metadata_path.is_file():
        raise RuntimeError("metadata missing: %s" % metadata_path)
    ground_truth = {}
    for item in read_jsonl(metadata_path):
        status = item.get("segmentation_review_status")
        if status not in FINAL_STATUSES:
            raise RuntimeError(
                "sample %s is not finally reviewed: %s"
                % (item.get("sample_id"), status)
            )
        image_name = Path(item["image"]).name
        boxes = item.get("segmentation_bbox_xyxy_px")
        if boxes is None:
            raise RuntimeError("reviewed boxes missing for %s" % image_name)
        ground_truth[image_name] = [[float(v) for v in box] for box in boxes]
    return ground_truth


def center_and_diagonal(box):
    x1, y1, x2, y2 = box
    return ((x1 + x2) / 2.0, (y1 + y2) / 2.0,
            math.hypot(x2 - x1, y2 - y1))


def candidate_distance(center, box, padding, min_distance, diagonal_scale):
    cx, cy = center
    x1, y1, x2, y2 = box
    bx, by, diagonal = center_and_diagonal(box)
    distance = math.hypot(cx - bx, cy - by)
    inside_padded = (
        x1 - padding <= cx <= x2 + padding
        and y1 - padding <= cy <= y2 + padding
    )
    close_enough = distance <= max(min_distance, diagonal_scale * diagonal)
    return distance if inside_padded or close_enough else None


def match_one_to_one(detections, boxes, padding, min_distance, diagonal_scale):
    candidates = []
    for detection_index, detection in enumerate(detections):
        center = [float(v) for v in detection["center_xy"]]
        for gt_index, box in enumerate(boxes):
            distance = candidate_distance(
                center, box, padding, min_distance, diagonal_scale)
            if distance is not None:
                candidates.append((distance, detection_index, gt_index))
    candidates.sort()
    used_detections = set()
    used_gt = set()
    matches = []
    for distance, detection_index, gt_index in candidates:
        if detection_index in used_detections or gt_index in used_gt:
            continue
        used_detections.add(detection_index)
        used_gt.add(gt_index)
        matches.append((detection_index, gt_index, distance))
    return matches


def intersection_coverage(roi, box):
    rx, ry, rw, rh = [float(v) for v in roi]
    x1, y1, x2, y2 = box
    intersection_w = max(0.0, min(rx + rw, x2) - max(rx, x1))
    intersection_h = max(0.0, min(ry + rh, y2) - max(ry, y1))
    area = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    return (intersection_w * intersection_h / area) if area else 0.0


def safe_divide(numerator, denominator):
    return numerator / denominator if denominator else 0.0


def evaluate(ground_truth, inference, padding, min_distance, diagonal_scale):
    inference_by_image = {item["image"]: item for item in inference["results"]}
    missing = sorted(set(ground_truth) - set(inference_by_image))
    unexpected = sorted(set(inference_by_image) - set(ground_truth))
    if missing or unexpected:
        raise RuntimeError(
            "image mismatch; missing=%s unexpected=%s" % (missing, unexpected))

    rows = []
    total_tp = total_fp = total_fn = 0
    coverages = []
    for image_name in sorted(ground_truth):
        boxes = ground_truth[image_name]
        detections = inference_by_image[image_name]["detections"]
        matches = match_one_to_one(
            detections, boxes, padding, min_distance, diagonal_scale)
        tp = len(matches)
        fp = len(detections) - tp
        fn = len(boxes) - tp
        total_tp += tp
        total_fp += fp
        total_fn += fn
        match_rows = []
        for detection_index, gt_index, distance in matches:
            detection = detections[detection_index]
            coverage = intersection_coverage(detection["roi_xywh"], boxes[gt_index])
            coverages.append(coverage)
            match_rows.append({
                "detection_index": detection_index,
                "gt_index": gt_index,
                "center_distance_px": distance,
                "score": detection["score"],
                "roi_gt_bbox_coverage": coverage,
            })
        rows.append({
            "image": image_name,
            "ground_truth_count": len(boxes),
            "detection_count": len(detections),
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "exact_count": len(boxes) == len(detections),
            "matches": match_rows,
        })

    precision = safe_divide(total_tp, total_tp + total_fp)
    recall = safe_divide(total_tp, total_tp + total_fn)
    return {
        "images": len(rows),
        "ground_truth_objects": total_tp + total_fn,
        "detections": total_tp + total_fp,
        "tp": total_tp,
        "fp": total_fp,
        "fn": total_fn,
        "precision": precision,
        "recall": recall,
        "f1": safe_divide(2.0 * precision * recall, precision + recall),
        "exact_count_images": sum(row["exact_count"] for row in rows),
        "exact_count_rate": safe_divide(
            sum(row["exact_count"] for row in rows), len(rows)),
        "matched_roi_mean_gt_bbox_coverage": safe_divide(
            sum(coverages), len(coverages)),
        "matched_roi_gt_bbox_coverage_at_least_90_rate": safe_divide(
            sum(value >= 0.9 for value in coverages), len(coverages)),
        "per_image": rows,
    }


def make_markdown(report):
    metrics = report["metrics"]
    lines = [
        "# Independent FOMO evaluation",
        "",
        "The threshold and ROI were fixed before scoring these reviewed images.",
        "",
        "- Images: %d" % metrics["images"],
        "- GT objects: %d" % metrics["ground_truth_objects"],
        "- TP / FP / FN: %d / %d / %d" % (
            metrics["tp"], metrics["fp"], metrics["fn"]),
        "- Precision / recall / F1: %.2f%% / %.2f%% / %.2f%%" % (
            metrics["precision"] * 100.0,
            metrics["recall"] * 100.0,
            metrics["f1"] * 100.0,
        ),
        "- Exact per-image count: %d/%d (%.2f%%)" % (
            metrics["exact_count_images"], metrics["images"],
            metrics["exact_count_rate"] * 100.0,
        ),
        "- Mean matched ROI coverage of GT bbox: %.2f%%" % (
            metrics["matched_roi_mean_gt_bbox_coverage"] * 100.0),
        "",
        "| Image | GT | Detected | TP | FP | FN | Exact |",
        "|---|---:|---:|---:|---:|---:|:---:|",
    ]
    for row in metrics["per_image"]:
        lines.append(
            "| {image} | {gt} | {det} | {tp} | {fp} | {fn} | {exact} |".format(
                image=row["image"], gt=row["ground_truth_count"],
                det=row["detection_count"], tp=row["tp"], fp=row["fp"],
                fn=row["fn"], exact="yes" if row["exact_count"] else "no",
            )
        )
    lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evaluation_session")
    parser.add_argument("inference_report")
    parser.add_argument("--output", required=True)
    parser.add_argument("--bbox-padding", type=float, default=12.0)
    parser.add_argument("--min-center-distance", type=float, default=24.0)
    parser.add_argument("--diagonal-scale", type=float, default=0.55)
    args = parser.parse_args()

    session_dir = Path(args.evaluation_session).resolve()
    inference_path = Path(args.inference_report).resolve()
    output_dir = Path(args.output).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    inference = json.loads(inference_path.read_text(encoding="utf-8"))
    ground_truth = load_ground_truth(session_dir)
    metrics = evaluate(
        ground_truth, inference, args.bbox_padding,
        args.min_center_distance, args.diagonal_scale)
    report = {
        "evaluation_session": session_dir.as_posix(),
        "inference_report": inference_path.as_posix(),
        "model": inference["model"],
        "threshold": inference["threshold"],
        "roi_size": inference["roi_size"],
        "matching": {
            "bbox_padding_px": args.bbox_padding,
            "min_center_distance_px": args.min_center_distance,
            "diagonal_scale": args.diagonal_scale,
            "one_to_one": True,
        },
        "metrics": metrics,
    }
    report_path = output_dir / "independent_gt_evaluation.json"
    summary_path = output_dir / "summary.md"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary_path.write_text(make_markdown(report), encoding="utf-8")
    print(json.dumps({
        key: metrics[key] for key in (
            "images", "ground_truth_objects", "tp", "fp", "fn",
            "precision", "recall", "f1", "exact_count_images",
        )
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
