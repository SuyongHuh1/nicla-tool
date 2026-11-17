"""Build a leakage-safe FOMO manifest from a reviewed capture session.

Images with the same configured group value always stay in the same split.
This script does not copy or modify source images, labels, masks, or inference
data.  The default profile is stool grouped by ``shape_id``, but the manifest
builder supports any metadata group field and any ordered class list.
"""

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path


SPLITS = ("train", "validation", "test")
DEFAULT_CLASS_NAMES = ("background", "stool")


def assert_training_session(session_dir):
    lowered = [part.lower() for part in session_dir.parts]
    if any(part == "checking" or part.startswith("inference") for part in lowered):
        raise RuntimeError("refusing to prepare a checking/inference folder")
    for name in ("metadata.jsonl", "images", "labels"):
        if not (session_dir / name).exists():
            raise RuntimeError("missing training session item: %s" % name)


def read_records(path):
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def read_yolo_boxes(path, class_names=DEFAULT_CLASS_NAMES):
    boxes = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        fields = line.split()
        if len(fields) != 5:
            raise RuntimeError("invalid YOLO row at %s:%d" % (path, line_number))
        source_class, cx, cy, width, height = fields
        values = [float(cx), float(cy), float(width), float(height)]
        output_class = int(source_class) + 1
        if output_class <= 0 or output_class >= len(class_names):
            raise RuntimeError(
                "source class %s is outside configured classes at %s:%d" %
                (source_class, path, line_number))
        if any(value < 0.0 or value > 1.0 for value in values):
            raise RuntimeError("YOLO value outside 0..1 at %s:%d" % (path, line_number))
        boxes.append({
            "class_id": output_class,
            "label": class_names[output_class],
            "bbox_yolo": values,
        })
    return boxes


def choose_group_splits(groups, validation_group=None, test_group=None):
    if len(groups) < 3:
        raise RuntimeError("at least three physical group IDs are required")
    validation_group = validation_group or groups[-2]
    test_group = test_group or groups[-1]
    if validation_group == test_group:
        raise RuntimeError("validation and test group must differ")
    if validation_group not in groups or test_group not in groups:
        raise RuntimeError("validation/test group is not present in the session")
    return {
        group: (
            "validation" if group == validation_group
            else "test" if group == test_group
            else "train"
        )
        for group in groups
    }


def choose_shape_splits(shapes, validation_shape=None, test_shape=None):
    """Backward-compatible stool profile wrapper."""
    return choose_group_splits(shapes, validation_shape, test_shape)


def make_manifest(session_dir, output_dir, source="labels", allow_pending=False,
                  validation_shape=None, test_shape=None, group_field="shape_id",
                  class_names=DEFAULT_CLASS_NAMES):
    assert_training_session(session_dir)
    if source not in ("labels", "labels_ai"):
        raise ValueError("source must be labels or labels_ai")
    label_dir = session_dir / source
    if not label_dir.is_dir():
        raise RuntimeError("label source not found: %s" % label_dir)

    class_names = tuple(class_names)
    if len(class_names) < 2 or class_names[0] != "background":
        raise RuntimeError("classes must start with background")
    if len(set(class_names)) != len(class_names):
        raise RuntimeError("class names must be unique")

    records = read_records(session_dir / "metadata.jsonl")
    groups = sorted({
        str(record.get(group_field)) for record in records
        if int(record.get("expected_instances", 0)) > 0
        and str(record.get(group_field, "")).lower() not in ("", "none", "baseline")
    })
    group_splits = choose_group_splits(groups, validation_shape, test_shape)

    rows = []
    issues = []
    status_counts = Counter()
    split_counts = Counter()
    split_shapes = defaultdict(set)
    excluded = 0
    for record in records:
        status = record.get("segmentation_review_status", "pending")
        status_counts[status] += 1
        if status == "excluded":
            excluded += 1
            continue
        if status == "pending" and not allow_pending:
            raise RuntimeError(
                "pending segmentation reviews remain; use --allow-pending only for a smoke test")

        sample_id = record["sample_id"]
        image_path = session_dir / record["image"]
        label_path = label_dir / (sample_id + ".txt")
        if not image_path.is_file() or not label_path.is_file():
            issues.append({"sample_id": sample_id, "issue": "missing image or label"})
            continue
        boxes = read_yolo_boxes(label_path, class_names)
        expected = int(record.get("expected_instances", 0))
        if len(boxes) != expected:
            issues.append({
                "sample_id": sample_id,
                "issue": "instance count mismatch",
                "expected": expected,
                "actual": len(boxes),
            })

        group_id = str(record.get(group_field, "none"))
        split = group_splits.get(group_id, "train")
        split_counts[split] += 1
        if expected:
            split_shapes[split].add(group_id)
        rows.append({
            "sample_id": sample_id,
            "image": image_path.resolve().as_posix(),
            "label_file": label_path.resolve().as_posix(),
            "group_field": group_field,
            "group_id": group_id,
            "shape_id": str(record.get("shape_id", "none")),
            "floor_id": record.get("floor_id"),
            "position_id": record.get("position_id"),
            "rotation": record.get("rotation"),
            "partial": record.get("partial"),
            "review_status": status,
            "split": split,
            "objects": boxes,
        })

    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "manifest.jsonl"
    with manifest_path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")

    summary = {
        "source_session": session_dir.resolve().as_posix(),
        "label_source": source,
        "class_names": list(class_names),
        "group_field": group_field,
        "sample_count": len(rows),
        "excluded_count": excluded,
        "status_counts": dict(sorted(status_counts.items())),
        "split_counts": {split: split_counts[split] for split in SPLITS},
        "split_shapes": {
            split: sorted(split_shapes[split]) for split in SPLITS
        },
        "split_groups": {
            split: sorted(split_shapes[split]) for split in SPLITS
        },
        "shape_splits": group_splits,
        "group_splits": group_splits,
        "issues": issues,
        "inference_folders_touched": 0,
        "smoke_only": bool(allow_pending),
    }
    (output_dir / "split_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest_path, summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("session_dir")
    parser.add_argument("--output", default="training_runs/fomo_stool_smoke")
    parser.add_argument("--source", choices=("labels", "labels_ai"), default="labels")
    parser.add_argument("--allow-pending", action="store_true")
    parser.add_argument("--group-field", default="shape_id")
    parser.add_argument("--classes", default=",".join(DEFAULT_CLASS_NAMES))
    parser.add_argument("--validation-group", "--validation-shape",
                        dest="validation_group")
    parser.add_argument("--test-group", "--test-shape", dest="test_group")
    args = parser.parse_args()
    manifest, summary = make_manifest(
        Path(args.session_dir).resolve(), Path(args.output).resolve(), args.source,
        args.allow_pending, args.validation_group, args.test_group,
        args.group_field,
        tuple(name.strip() for name in args.classes.split(",") if name.strip()))
    print("Created %s" % manifest)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
