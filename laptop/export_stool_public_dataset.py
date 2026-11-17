"""Export a minimal, path-clean stool dataset for reproducible training.

Only finally reviewed images, masks, and labels are copied. Intermediate AI
artifacts, previews, backups, and local absolute paths are deliberately left
out. Exact duplicate images are retained once and recorded in the summary.
"""

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
import shutil


FINAL_STATUSES = {"accepted", "corrected"}
PUBLIC_FIELDS = (
    "sample_id",
    "captured_at",
    "frame_sequence",
    "image_size",
    "capture_mode",
    "shape_id",
    "floor_id",
    "floor_material",
    "position_id",
    "rotation",
    "lighting",
    "partial",
    "dataset_role",
    "allow_multiple_instances",
    "expected_instances",
    "segmentation_review_status",
    "segmentation_mask_pixels",
    "segmentation_bbox_xyxy_px",
)


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_jsonl(path):
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def resolve_source(session, record, field, fallback_dir, suffix):
    relative = record.get(field)
    if relative:
        path = session / relative
    else:
        path = session / fallback_dir / (record["sample_id"] + suffix)
    if not path.is_file():
        raise RuntimeError("missing %s for %s: %s" % (
            field, record["sample_id"], path))
    return path


def public_record(record, image_name, mask_name, label_name):
    output = {
        key: record[key]
        for key in PUBLIC_FIELDS
        if key in record
    }
    output["image"] = "images/" + image_name
    output["mask"] = "masks/" + mask_name
    output["label"] = "labels/" + label_name
    return output


def export_session(source, destination, seen_images):
    records = read_jsonl(source / "metadata.jsonl")
    for name in ("images", "masks", "labels"):
        (destination / name).mkdir(parents=True, exist_ok=True)

    exported = []
    duplicates = []
    statuses = Counter()
    shapes = Counter()
    for record in records:
        sample_id = record["sample_id"]
        status = record.get("segmentation_review_status", "pending")
        if status not in FINAL_STATUSES:
            raise RuntimeError(
                "sample %s is not finally reviewed: %s" % (sample_id, status))

        image = resolve_source(source, record, "image", "images", ".jpg")
        mask = resolve_source(source, record, "mask", "masks", ".png")
        label = resolve_source(source, record, "label", "labels", ".txt")
        image_hash = sha256(image)
        if image_hash in seen_images:
            duplicates.append({
                "sample_id": sample_id,
                "duplicate_of": seen_images[image_hash],
                "sha256": image_hash,
            })
            continue
        seen_images[image_hash] = sample_id

        image_name = sample_id + image.suffix.lower()
        mask_name = sample_id + mask.suffix.lower()
        label_name = sample_id + ".txt"
        shutil.copy2(image, destination / "images" / image_name)
        shutil.copy2(mask, destination / "masks" / mask_name)
        shutil.copy2(label, destination / "labels" / label_name)
        exported.append(public_record(record, image_name, mask_name, label_name))
        statuses[status] += 1
        shapes[str(record.get("shape_id", "none"))] += 1

    metadata = destination / "metadata.jsonl"
    with metadata.open("w", encoding="utf-8", newline="\n") as stream:
        for record in exported:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
    return {
        "source_records": len(records),
        "exported_records": len(exported),
        "exact_duplicates_removed": len(duplicates),
        "duplicates": duplicates,
        "status_counts": dict(sorted(statuses.items())),
        "shape_counts": dict(sorted(shapes.items())),
    }


def write_checksums(root):
    rows = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        if path.name == "checksums.sha256":
            continue
        rows.append("%s  %s" % (sha256(path), path.relative_to(root).as_posix()))
    (root / "checksums.sha256").write_text(
        "\n".join(rows) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--training-session", required=True)
    parser.add_argument("--evaluation-session", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    training = Path(args.training_session).resolve()
    evaluation = Path(args.evaluation_session).resolve()
    output = Path(args.output).resolve()
    if output.exists() and any(output.iterdir()):
        raise RuntimeError("output must be absent or empty: %s" % output)
    output.mkdir(parents=True, exist_ok=True)

    seen_images = {}
    summary = {
        "dataset_version": "v1",
        "training": export_session(training, output / "train", seen_images),
        "evaluation": export_session(
            evaluation, output / "evaluation" / "inference_e01", seen_images),
    }
    summary["total_exported_images"] = (
        summary["training"]["exported_records"]
        + summary["evaluation"]["exported_records"])
    summary["local_paths_removed"] = True
    summary["intermediate_artifacts_included"] = False
    (output / "dataset_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    write_checksums(output)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
