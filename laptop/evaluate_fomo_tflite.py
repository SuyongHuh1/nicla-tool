"""Run a quantized FOMO model on untouched checking/inference images."""

import argparse
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np


def assert_inference_session(session_dir):
    lowered = [part.lower() for part in session_dir.parts]
    if not any(part == "checking" or part.startswith("inference") for part in lowered):
        raise RuntimeError("input must be a checking/inference session")
    image_dir = session_dir / "images" if (session_dir / "images").is_dir() else session_dir
    if not image_dir.is_dir():
        raise RuntimeError("inference image folder not found: %s" % image_dir)
    return image_dir


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


def center_roi(cx, cy, size, image_w, image_h):
    rw, rh = size
    rw, rh = min(int(rw), image_w), min(int(rh), image_h)
    x = max(0, min(image_w - rw, int(round(cx)) - rw // 2))
    y = max(0, min(image_h - rh, int(round(cy)) - rh // 2))
    return [x, y, rw, rh]


def decode_fomo(stool_probability, threshold, image_w, image_h, roi_size=(112, 112)):
    binary = (stool_probability >= threshold).astype(np.uint8)
    count, labels = cv2.connectedComponents(binary, connectivity=8)
    detections = []
    grid_h, grid_w = stool_probability.shape
    for component in range(1, count):
        ys, xs = np.where(labels == component)
        if not len(xs):
            continue
        component_scores = stool_probability[ys, xs]
        score_sum = float(component_scores.sum())
        cx_grid = float(np.sum((xs + 0.5) * component_scores) / score_sum)
        cy_grid = float(np.sum((ys + 0.5) * component_scores) / score_sum)
        cx = cx_grid / grid_w * image_w
        cy = cy_grid / grid_h * image_h
        detections.append({
            "score": float(component_scores.max()),
            "cells": int(len(xs)),
            "center_xy": [float(cx), float(cy)],
            "roi_xywh": center_roi(cx, cy, roi_size, image_w, image_h),
        })
    detections.sort(key=lambda detection: detection["score"], reverse=True)
    top_y, top_x = np.unravel_index(np.argmax(stool_probability), stool_probability.shape)
    top_center = [
        float((top_x + 0.5) / grid_w * image_w),
        float((top_y + 0.5) / grid_h * image_h),
    ]
    return detections, {
        "score": float(stool_probability[top_y, top_x]),
        "center_xy": top_center,
    }


def draw_result(image, detections, top_candidate, threshold, class_name):
    canvas = image.copy()
    for detection in detections:
        x, y, w, h = detection["roi_xywh"]
        cx, cy = [int(round(value)) for value in detection["center_xy"]]
        cv2.rectangle(canvas, (x, y), (x + w, y + h), (0, 220, 255), 2)
        cv2.drawMarker(canvas, (cx, cy), (0, 0, 255), cv2.MARKER_CROSS, 18, 2)
        cv2.putText(canvas, "%s %.2f" % (class_name, detection["score"]),
                    (max(2, x), max(14, y - 5)), cv2.FONT_HERSHEY_SIMPLEX,
                    0.5, (0, 0, 255), 1, cv2.LINE_AA)
    if not detections:
        cx, cy = [int(round(value)) for value in top_candidate["center_xy"]]
        cv2.drawMarker(canvas, (cx, cy), (150, 150, 150), cv2.MARKER_CROSS, 14, 1)
        cv2.putText(canvas, "no detection; top %.2f < %.2f" % (
            top_candidate["score"], threshold), (5, 18), cv2.FONT_HERSHEY_SIMPLEX,
            0.45, (40, 40, 220), 1, cv2.LINE_AA)
    return canvas


def make_contact_sheet(overlays, captions, destination):
    if not overlays:
        return
    tile_w, tile_h = 320, 270
    columns = 3
    rows = int(np.ceil(len(overlays) / columns))
    sheet = np.full((rows * tile_h, columns * tile_w, 3), 240, np.uint8)
    for index, (overlay, caption) in enumerate(zip(overlays, captions)):
        tile = cv2.resize(overlay, (tile_w, 240), interpolation=cv2.INTER_AREA)
        x, y = (index % columns) * tile_w, (index // columns) * tile_h
        sheet[y:y + 240, x:x + tile_w] = tile
        cv2.putText(sheet, caption, (x + 5, y + 261), cv2.FONT_HERSHEY_SIMPLEX,
                    0.48, (20, 20, 20), 1, cv2.LINE_AA)
    ok, encoded = cv2.imencode(".jpg", sheet, [cv2.IMWRITE_JPEG_QUALITY, 92])
    if not ok:
        raise RuntimeError("failed to encode contact sheet")
    encoded.tofile(str(destination))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("session_dir")
    parser.add_argument("--model", default="models/fomo_stool_smoke.tflite")
    parser.add_argument("--output", default="training_runs/fomo_stool_smoke/inference_checking")
    parser.add_argument("--threshold", type=float, default=0.55)
    parser.add_argument("--roi-width", type=int, default=112)
    parser.add_argument("--roi-height", type=int, default=112)
    parser.add_argument("--class-id", type=int, default=1)
    parser.add_argument("--class-name", default="stool")
    args = parser.parse_args()

    session_dir = Path(args.session_dir).resolve()
    image_dir = assert_inference_session(session_dir)
    image_paths = sorted(
        path for path in image_dir.iterdir()
        if path.suffix.lower() in (".jpg", ".jpeg", ".png", ".bmp"))
    if not image_paths:
        raise RuntimeError("no inference images found")
    before_hashes = {path.name: file_hash(path) for path in image_paths}

    try:
        import tensorflow as tf
    except ImportError as error:
        raise RuntimeError("TensorFlow is required for host-side TFLite checking") from error
    model_path = Path(args.model)
    interpreter = tf.lite.Interpreter(model_content=model_path.read_bytes())
    interpreter.allocate_tensors()
    input_detail = interpreter.get_input_details()[0]
    output_detail = interpreter.get_output_details()[0]
    input_scale, input_zero = input_detail["quantization"]
    output_scale, output_zero = output_detail["quantization"]
    input_h, input_w = [int(value) for value in input_detail["shape"][1:3]]
    output_classes = int(output_detail["shape"][-1])
    if args.class_id <= 0 or args.class_id >= output_classes:
        raise RuntimeError(
            "class id %d is outside model output range 1..%d" % (
                args.class_id, output_classes - 1))

    output_dir = Path(args.output).resolve()
    overlay_dir = output_dir / "overlays"
    overlay_dir.mkdir(parents=True, exist_ok=True)
    results, overlays, captions = [], [], []
    for path in image_paths:
        image = read_image(path)
        image_h, image_w = image.shape[:2]
        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        resized = cv2.resize(rgb, (input_w, input_h), interpolation=cv2.INTER_AREA)
        quantized = np.clip(
            np.rint(resized.astype(np.float32) / input_scale + input_zero),
            0, 255).astype(np.uint8)
        interpreter.set_tensor(input_detail["index"], quantized[None, ...])
        interpreter.invoke()
        output = interpreter.get_tensor(output_detail["index"])[0].astype(np.float32)
        output = (output - output_zero) * output_scale
        class_probability = output[..., args.class_id]
        detections, top_candidate = decode_fomo(
            class_probability, args.threshold, image_w, image_h,
            (args.roi_width, args.roi_height))
        overlay = draw_result(
            image, detections, top_candidate, args.threshold, args.class_name)
        overlay_path = overlay_dir / (path.stem + ".jpg")
        ok, encoded = cv2.imencode(".jpg", overlay, [cv2.IMWRITE_JPEG_QUALITY, 94])
        if not ok:
            raise RuntimeError("failed to encode overlay: %s" % path)
        encoded.tofile(str(overlay_path))
        results.append({
            "image": path.name,
            "detections": detections,
            "top_candidate": top_candidate,
        })
        overlays.append(overlay)
        captions.append("%s  det=%d top=%.2f" % (
            path.stem, len(detections), top_candidate["score"]))

    after_hashes = {path.name: file_hash(path) for path in image_paths}
    unchanged = before_hashes == after_hashes
    detection_images = sum(bool(result["detections"]) for result in results)
    scores = [result["top_candidate"]["score"] for result in results]
    report = {
        "purpose": "read-only smoke inference; no ground truth",
        "source_session": session_dir.as_posix(),
        "model": Path(args.model).resolve().as_posix(),
        "threshold": args.threshold,
        "class_id": args.class_id,
        "class_name": args.class_name,
        "roi_size": [args.roi_width, args.roi_height],
        "image_count": len(results),
        "images_with_detection": detection_images,
        "total_detections": sum(len(result["detections"]) for result in results),
        "top_score_min": float(min(scores)),
        "top_score_mean": float(np.mean(scores)),
        "top_score_max": float(max(scores)),
        "source_files_unchanged": unchanged,
        "source_sha256": before_hashes,
        "results": results,
    }
    (output_dir / "inference_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    make_contact_sheet(overlays, captions, output_dir / "contact_sheet.jpg")
    print(json.dumps({key: report[key] for key in (
        "image_count", "images_with_detection", "total_detections",
        "top_score_min", "top_score_mean", "top_score_max",
        "source_files_unchanged")}, indent=2))


if __name__ == "__main__":
    main()
