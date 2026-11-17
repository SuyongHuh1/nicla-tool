"""Validate a quantized FOMO stool detector without tuning on the test split.

The detection threshold is selected on the validation split and then locked for
the held-out test split.  This script never writes into the source dataset.
"""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np

from evaluate_fomo_tflite import center_roi, decode_fomo


GRID_SIZE = 12
DEFAULT_THRESHOLDS = tuple(round(value / 100.0, 2) for value in range(30, 91, 5))


def row_group(row):
    return str(row.get("group_id", row.get("shape_id", "unknown")))


def read_manifest(path):
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def file_hash(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_image(path):
    encoded = np.fromfile(str(path), dtype=np.uint8)
    image = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
    if image is None:
        raise RuntimeError("cannot decode image: %s" % path)
    return image


def ground_truth_centers(row, class_id):
    centers = []
    for obj in row["objects"]:
        if int(obj["class_id"]) != class_id:
            continue
        cx, cy = [float(value) for value in obj["bbox_yolo"][:2]]
        grid_x = min(GRID_SIZE - 1, max(0, int(cx * GRID_SIZE)))
        grid_y = min(GRID_SIZE - 1, max(0, int(cy * GRID_SIZE)))
        centers.append([grid_x + 0.5, grid_y + 0.5])
    return centers


def greedy_match(gt_centers, predicted_centers, tolerance):
    candidates = []
    for gt_index, gt in enumerate(gt_centers):
        for pred_index, pred in enumerate(predicted_centers):
            distance = float(np.hypot(gt[0] - pred[0], gt[1] - pred[1]))
            candidates.append((distance, gt_index, pred_index))
    matched_gt, matched_pred, matches = set(), set(), []
    for distance, gt_index, pred_index in sorted(candidates):
        if distance > tolerance:
            break
        if gt_index in matched_gt or pred_index in matched_pred:
            continue
        matched_gt.add(gt_index)
        matched_pred.add(pred_index)
        matches.append({
            "gt_index": gt_index,
            "prediction_index": pred_index,
            "cell_error": distance,
        })
    return matches


def evaluate_probabilities(rows, probabilities, threshold, class_id,
                           tolerance=np.sqrt(2.0), include_details=False):
    tp = fp = fn = exact_count = 0
    match_errors = []
    top_errors = []
    top_within_one = 0
    positive_samples = 0
    details = []
    for row, probability in zip(rows, probabilities):
        detections, top_candidate = decode_fomo(
            probability, threshold, GRID_SIZE, GRID_SIZE, (1, 1))
        gt_centers = ground_truth_centers(row, class_id)
        predicted_centers = [item["center_xy"] for item in detections]
        matches = greedy_match(gt_centers, predicted_centers, tolerance)
        sample_tp = len(matches)
        sample_fp = len(predicted_centers) - sample_tp
        sample_fn = len(gt_centers) - sample_tp
        tp += sample_tp
        fp += sample_fp
        fn += sample_fn
        exact_count += int(len(gt_centers) == len(predicted_centers))
        match_errors.extend(match["cell_error"] for match in matches)

        if gt_centers:
            positive_samples += 1
            top_center = top_candidate["center_xy"]
            top_error = min(float(np.hypot(
                top_center[0] - gt[0], top_center[1] - gt[1])) for gt in gt_centers)
            top_errors.append(top_error)
            top_within_one += int(top_error <= tolerance)
        else:
            top_error = None

        if include_details:
            details.append({
                "sample_id": row["sample_id"],
                "group_id": row_group(row),
                "ground_truth_count": len(gt_centers),
                "prediction_count": len(predicted_centers),
                "true_positives": sample_tp,
                "false_positives": sample_fp,
                "false_negatives": sample_fn,
                "top_score": float(top_candidate["score"]),
                "top_cell_error": top_error,
                "ground_truth_centers": gt_centers,
                "predicted_centers": predicted_centers,
                "matches": matches,
            })

    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2.0 * precision * recall / (precision + recall) if precision + recall else 0.0
    result = {
        "samples": len(rows),
        "positive_samples": positive_samples,
        "ground_truth_objects": tp + fn,
        "predicted_objects": tp + fp,
        "true_positives": tp,
        "false_positives": fp,
        "false_negatives": fn,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "exact_count_rate": exact_count / len(rows) if rows else 0.0,
        "mean_matched_cell_error": float(np.mean(match_errors)) if match_errors else None,
        "top_within_one_cell_rate": (
            top_within_one / positive_samples if positive_samples else None),
        "mean_top_cell_error": float(np.mean(top_errors)) if top_errors else None,
        "false_positives_per_image": fp / len(rows) if rows else 0.0,
    }
    if include_details:
        result["details"] = details
    return result


def choose_threshold(rows, probabilities, class_id, thresholds=DEFAULT_THRESHOLDS):
    sweep = []
    for threshold in thresholds:
        metrics = evaluate_probabilities(rows, probabilities, threshold, class_id)
        sweep.append({"threshold": threshold, **metrics})
    # Prefer F1, then exact object count, then fewer false positives.  A higher
    # threshold is the final tie-breaker so weak activations are not retained.
    selected = max(sweep, key=lambda item: (
        item["f1"], item["exact_count_rate"], -item["false_positives"],
        item["threshold"]))
    return selected["threshold"], sweep


def split_integrity(rows):
    sample_sets = {
        split: {row["sample_id"] for row in rows if row["split"] == split}
        for split in ("train", "validation", "test")
    }
    group_sets = {
        split: {row_group(row) for row in rows if row["split"] == split
                and row_group(row).lower() not in ("none", "baseline", "empty")}
        for split in ("train", "validation", "test")
    }
    sample_overlap = sorted(
        (sample_sets["train"] & sample_sets["validation"])
        | (sample_sets["train"] & sample_sets["test"])
        | (sample_sets["validation"] & sample_sets["test"]))
    group_overlap = sorted(
        (group_sets["train"] & group_sets["validation"])
        | (group_sets["train"] & group_sets["test"])
        | (group_sets["validation"] & group_sets["test"]))
    group_field = next((row.get("group_field") for row in rows
                        if row.get("group_field")), "shape_id")
    return {
        "sample_id_overlap": sample_overlap,
        "group_id_overlap": group_overlap,
        "shape_id_overlap": group_overlap,
        "leakage_free": not sample_overlap and not group_overlap,
        "group_field": group_field,
        "groups": {key: sorted(value) for key, value in group_sets.items()},
        "shapes": {key: sorted(value) for key, value in group_sets.items()},
    }


def roi_coverage_sweep(rows, details, class_id, roi_sizes):
    """Measure how much GT bounding-box area a centered square ROI retains."""
    detail_by_sample = {detail["sample_id"]: detail for detail in details}
    coverages = {size: [] for size in roi_sizes}
    all_gt_counts = 0
    matched_counts = 0
    for row in rows:
        detail = detail_by_sample[row["sample_id"]]
        image = read_image(Path(row["image"]))
        image_h, image_w = image.shape[:2]
        objects = [obj for obj in row["objects"]
                   if int(obj["class_id"]) == class_id]
        all_gt_counts += len(objects)
        matches_by_gt = {match["gt_index"]: match for match in detail["matches"]}
        for gt_index, obj in enumerate(objects):
            match = matches_by_gt.get(gt_index)
            if match is None:
                for size in roi_sizes:
                    coverages[size].append((0.0, False))
                continue
            matched_counts += 1
            pred = detail["predicted_centers"][match["prediction_index"]]
            pred_x = pred[0] / GRID_SIZE * image_w
            pred_y = pred[1] / GRID_SIZE * image_h
            cx, cy, width, height = [float(value) for value in obj["bbox_yolo"]]
            gt_x0 = max(0.0, (cx - width / 2.0) * image_w)
            gt_y0 = max(0.0, (cy - height / 2.0) * image_h)
            gt_x1 = min(float(image_w), (cx + width / 2.0) * image_w)
            gt_y1 = min(float(image_h), (cy + height / 2.0) * image_h)
            gt_area = max(0.0, gt_x1 - gt_x0) * max(0.0, gt_y1 - gt_y0)
            for size in roi_sizes:
                roi_x, roi_y, roi_w, roi_h = center_roi(
                    pred_x, pred_y, (size, size), image_w, image_h)
                roi_x1, roi_y1 = roi_x + roi_w, roi_y + roi_h
                intersection = max(0.0, min(gt_x1, roi_x1) - max(gt_x0, roi_x)) * max(
                    0.0, min(gt_y1, roi_y1) - max(gt_y0, roi_y))
                coverage = intersection / gt_area if gt_area else 0.0
                contained = coverage >= 0.999
                coverages[size].append((coverage, contained))

    result = []
    for size in roi_sizes:
        values = coverages[size]
        detected_values = [coverage for coverage, _contained in values if coverage > 0.0]
        result.append({
            "roi_size": [size, size],
            "all_gt_objects": all_gt_counts,
            "matched_gt_objects": matched_counts,
            "mean_bbox_coverage_all_gt": float(np.mean(
                [coverage for coverage, _contained in values])) if values else None,
            "bbox_coverage_at_least_90_all_gt_rate": (
                sum(coverage >= 0.90 for coverage, _contained in values) / len(values)
                if values else None),
            "mean_bbox_coverage_when_detected": (
                float(np.mean(detected_values)) if detected_values else None),
            "bbox_coverage_at_least_90_when_detected_rate": (
                sum(coverage >= 0.90 for coverage in detected_values) / len(detected_values)
                if detected_values else None),
            "full_bbox_containment_when_detected_rate": (
                sum(contained for coverage, contained in values if coverage > 0.0)
                / len(detected_values) if detected_values else None),
        })
    return result


def load_tflite_probabilities(rows, model_path, class_id):
    try:
        import tensorflow as tf
    except ImportError as error:
        raise RuntimeError("TensorFlow is required for TFLite validation") from error

    interpreter = tf.lite.Interpreter(model_content=model_path.read_bytes())
    interpreter.allocate_tensors()
    input_detail = interpreter.get_input_details()[0]
    output_detail = interpreter.get_output_details()[0]
    input_scale, input_zero = input_detail["quantization"]
    output_scale, output_zero = output_detail["quantization"]
    input_h, input_w = [int(value) for value in input_detail["shape"][1:3]]
    output_shape = [int(value) for value in output_detail["shape"]]
    if output_shape[1:3] != [GRID_SIZE, GRID_SIZE]:
        raise RuntimeError("expected a 12x12 FOMO output, got %r" % output_shape)
    if class_id <= 0 or class_id >= output_shape[-1]:
        raise RuntimeError("class id is outside model output: %d" % class_id)

    probabilities = []
    for row in rows:
        image = read_image(Path(row["image"]))
        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        resized = cv2.resize(rgb, (input_w, input_h), interpolation=cv2.INTER_AREA)
        quantized = np.clip(
            np.rint(resized.astype(np.float32) / input_scale + input_zero),
            0, 255).astype(np.uint8)
        interpreter.set_tensor(input_detail["index"], quantized[None, ...])
        interpreter.invoke()
        output = interpreter.get_tensor(output_detail["index"])[0].astype(np.float32)
        output = (output - output_zero) * output_scale
        probabilities.append(output[..., class_id])
    return probabilities, {
        "input_shape": [int(value) for value in input_detail["shape"]],
        "input_dtype": str(input_detail["dtype"]),
        "output_shape": output_shape,
        "output_dtype": str(output_detail["dtype"]),
    }


def write_contact_sheet(path, rows, details, failures_only=False, roi_size=112):
    selected = []
    by_sample = {detail["sample_id"]: detail for detail in details}
    for row in rows:
        detail = by_sample[row["sample_id"]]
        is_failure = detail["false_positives"] or detail["false_negatives"]
        if failures_only and not is_failure:
            continue
        selected.append((row, detail))
    if not selected:
        return False

    tile_w, image_h, caption_h = 240, 180, 38
    columns = 4
    sheet_rows = int(np.ceil(len(selected) / columns))
    sheet = np.full((sheet_rows * (image_h + caption_h), columns * tile_w, 3),
                    238, np.uint8)
    for index, (row, detail) in enumerate(selected):
        image = read_image(Path(row["image"]))
        source_h, source_w = image.shape[:2]
        for center in detail["ground_truth_centers"]:
            x = int(round(center[0] / GRID_SIZE * source_w))
            y = int(round(center[1] / GRID_SIZE * source_h))
            cv2.drawMarker(image, (x, y), (0, 210, 0), cv2.MARKER_TILTED_CROSS, 20, 2)
        for center in detail["predicted_centers"]:
            x = int(round(center[0] / GRID_SIZE * source_w))
            y = int(round(center[1] / GRID_SIZE * source_h))
            rx, ry, rw, rh = center_roi(
                x, y, (roi_size, roi_size), source_w, source_h)
            cv2.rectangle(image, (rx, ry), (rx + rw, ry + rh), (0, 210, 255), 2)
            cv2.drawMarker(image, (x, y), (0, 0, 230), cv2.MARKER_CROSS, 18, 2)
        tile = cv2.resize(image, (tile_w, image_h), interpolation=cv2.INTER_AREA)
        x0 = (index % columns) * tile_w
        y0 = (index // columns) * (image_h + caption_h)
        sheet[y0:y0 + image_h, x0:x0 + tile_w] = tile
        caption1 = "%s  GT=%d pred=%d" % (
            row_group(row), detail["ground_truth_count"], detail["prediction_count"])
        caption2 = "TP=%d FP=%d FN=%d top=%.2f" % (
            detail["true_positives"], detail["false_positives"],
            detail["false_negatives"], detail["top_score"])
        cv2.putText(sheet, caption1, (x0 + 4, y0 + image_h + 15),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.42, (20, 20, 20), 1, cv2.LINE_AA)
        cv2.putText(sheet, caption2, (x0 + 4, y0 + image_h + 32),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.40, (20, 20, 20), 1, cv2.LINE_AA)
    ok, encoded = cv2.imencode(".jpg", sheet, [cv2.IMWRITE_JPEG_QUALITY, 92])
    if not ok:
        raise RuntimeError("failed to encode validation contact sheet")
    encoded.tofile(str(path))
    return True


def markdown_summary(report):
    validation = report["validation"]
    test = report["test"]
    reasons = "\n".join("- " + reason for reason in report["not_final_reasons"])
    validation_groups = ", ".join(
        report["split_integrity"]["groups"]["validation"])
    test_groups = ", ".join(report["split_integrity"]["groups"]["test"])
    roi_rows = "\n".join(
        "| {size} | {mean:.1%} | {at90:.1%} | {full:.1%} | {end_to_end:.1%} |".format(
            size=item["roi_size"][0],
            mean=item["mean_bbox_coverage_when_detected"] or 0.0,
            at90=item["bbox_coverage_at_least_90_when_detected_rate"] or 0.0,
            full=item["full_bbox_containment_when_detected_rate"] or 0.0,
            end_to_end=item["bbox_coverage_at_least_90_all_gt_rate"] or 0.0,
        ) for item in report["test_roi_sweep"])
    return """# FOMO validation: {class_name}

Status: **{status}**

The threshold was selected only on validation group(s) `{validation_groups}`
and then locked for held-out test group(s) `{test_groups}`.

| Split | Samples | Precision | Recall | F1 | Exact count | Top center <= 1 cell | FP/image |
|---|---:|---:|---:|---:|---:|---:|---:|
| validation | {v_samples} | {v_precision:.1%} | {v_recall:.1%} | {v_f1:.1%} | {v_count:.1%} | {v_center:.1%} | {v_fp:.3f} |
| test | {t_samples} | {t_precision:.1%} | {t_recall:.1%} | {t_f1:.1%} | {t_count:.1%} | {t_center:.1%} | {t_fp:.3f} |

- Selected threshold: `{threshold:.2f}`
- Split leakage check: `{leakage}`
- Test source images unchanged: `{unchanged}`
- Review states in manifest: `{reviews}`

## Test ROI coverage

Coverage is measured against the current GT bounding boxes. Missed detections
count as zero in the end-to-end column.

| Square ROI px | Mean coverage when detected | >=90% when detected | Full containment when detected | End-to-end >=90% |
|---:|---:|---:|---:|---:|
{roi_rows}

## Why this is not a final acceptance result

{reasons}
""".format(
        status=report["status"],
        class_name=report["class_name"],
        validation_groups=validation_groups,
        test_groups=test_groups,
        v_samples=validation["samples"],
        v_precision=validation["precision"],
        v_recall=validation["recall"],
        v_f1=validation["f1"],
        v_count=validation["exact_count_rate"],
        v_center=validation["top_within_one_cell_rate"] or 0.0,
        v_fp=validation["false_positives_per_image"],
        t_samples=test["samples"],
        t_precision=test["precision"],
        t_recall=test["recall"],
        t_f1=test["f1"],
        t_count=test["exact_count_rate"],
        t_center=test["top_within_one_cell_rate"] or 0.0,
        t_fp=test["false_positives_per_image"],
        threshold=report["selected_threshold"],
        leakage=str(report["split_integrity"]["leakage_free"]).lower(),
        unchanged=str(report["source_files_unchanged"]).lower(),
        reviews=json.dumps(report["review_status_counts"], ensure_ascii=False),
        roi_rows=roi_rows,
        reasons=reasons,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest")
    parser.add_argument("--model", default="models/fomo_stool_smoke.tflite")
    parser.add_argument("--output", default="training_runs/fomo_stool_smoke/validation")
    parser.add_argument("--class-id", type=int, default=1)
    parser.add_argument("--class-name", default="stool")
    parser.add_argument(
        "--roi-sizes", default="96,112,128,144,160,176,192,208,224")
    parser.add_argument("--display-roi-size", type=int, default=112)
    args = parser.parse_args()

    manifest_path = Path(args.manifest).resolve()
    model_path = Path(args.model).resolve()
    output_dir = Path(args.output).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = read_manifest(manifest_path)
    if not rows:
        raise RuntimeError("manifest is empty")
    integrity = split_integrity(rows)
    if not integrity["leakage_free"]:
        raise RuntimeError("train/validation/test leakage detected")

    selected_rows = [row for row in rows if row["split"] in ("validation", "test")]
    before_hashes = {row["sample_id"]: file_hash(Path(row["image"]))
                     for row in selected_rows}
    probabilities, tensor_details = load_tflite_probabilities(
        selected_rows, model_path, args.class_id)
    probability_by_sample = dict(zip(
        [row["sample_id"] for row in selected_rows], probabilities))
    val_rows = [row for row in rows if row["split"] == "validation"]
    test_rows = [row for row in rows if row["split"] == "test"]
    val_probabilities = [probability_by_sample[row["sample_id"]] for row in val_rows]
    test_probabilities = [probability_by_sample[row["sample_id"]] for row in test_rows]
    threshold, sweep = choose_threshold(
        val_rows, val_probabilities, args.class_id)
    validation = evaluate_probabilities(
        val_rows, val_probabilities, threshold, args.class_id, include_details=True)
    test = evaluate_probabilities(
        test_rows, test_probabilities, threshold, args.class_id, include_details=True)
    roi_sizes = tuple(sorted(set(
        int(value.strip()) for value in args.roi_sizes.split(",") if value.strip())))
    if not roi_sizes or min(roi_sizes) <= 0:
        raise RuntimeError("ROI sizes must be positive integers")
    test_roi_sweep = roi_coverage_sweep(
        test_rows, test["details"], args.class_id, roi_sizes)

    write_contact_sheet(
        output_dir / "validation_failures.jpg", val_rows,
        validation["details"], failures_only=True,
        roi_size=args.display_roi_size)
    write_contact_sheet(
        output_dir / "test_all.jpg", test_rows, test["details"], failures_only=False,
        roi_size=args.display_roi_size)
    failures_written = write_contact_sheet(
        output_dir / "test_failures.jpg", test_rows, test["details"], failures_only=True,
        roi_size=args.display_roi_size)
    after_hashes = {row["sample_id"]: file_hash(Path(row["image"]))
                    for row in selected_rows}
    review_counts = dict(sorted(Counter(
        row.get("review_status", "pending") for row in rows).items()))
    independent_negative_count = sum(
        not any(int(obj["class_id"]) == args.class_id for obj in row["objects"])
        for row in test_rows)
    reasons = []
    if review_counts.get("pending", 0):
        reasons.append("Human segmentation review is incomplete (%d pending labels)." %
                       review_counts["pending"])
    if independent_negative_count == 0:
        reasons.append("The held-out test split has no empty/background images, so false-positive rejection is not independently measured.")
    reasons.append("Nicla Vision memory, FPS, temperature, and live-camera behavior require an on-board run after reconnecting the board.")
    report = {
        "purpose": "quantized host-side FOMO validation",
        "status": "PROVISIONAL" if reasons else "READY_FOR_BOARD_VALIDATION",
        "manifest": manifest_path.as_posix(),
        "model": model_path.as_posix(),
        "model_sha256": file_hash(model_path),
        "class_id": args.class_id,
        "class_name": args.class_name,
        "selected_threshold": threshold,
        "threshold_selection_split": "validation",
        "threshold_sweep": sweep,
        "split_integrity": integrity,
        "review_status_counts": review_counts,
        "independent_test_negative_images": independent_negative_count,
        "tensor_details": tensor_details,
        "validation": validation,
        "test": test,
        "test_roi_sweep": test_roi_sweep,
        "display_roi_size": [args.display_roi_size, args.display_roi_size],
        "source_files_unchanged": before_hashes == after_hashes,
        "test_failures_sheet_written": failures_written,
        "not_final_reasons": reasons,
    }
    report_path = output_dir / "validation_report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output_dir / "summary.md").write_text(markdown_summary(report), encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        "selected_threshold": threshold,
        "validation": {key: validation[key] for key in (
            "precision", "recall", "f1", "exact_count_rate",
            "top_within_one_cell_rate", "false_positives_per_image")},
        "test": {key: test[key] for key in (
            "precision", "recall", "f1", "exact_count_rate",
            "top_within_one_cell_rate", "false_positives_per_image")},
        "source_files_unchanged": report["source_files_unchanged"],
        "summary": (output_dir / "summary.md").as_posix(),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
