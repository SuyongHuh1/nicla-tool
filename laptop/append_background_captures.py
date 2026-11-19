"""Append reviewed empty/background captures to an existing FOMO manifest.

The source manifest and images are never modified.  Captures are ordered by
filename so an early acquisition batch can be reserved as a held-out test set
while later captures are used for training.
"""

import argparse
import json
from collections import Counter
from pathlib import Path


def read_jsonl(path):
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def append_background(base_manifest, captures, output, test_first=0,
                      validation_last=0,
                      train_group="background_capture_train",
                      test_group="background_capture_test",
                      validation_group="background_capture_validation",
                      lighting=None, floor_id=None):
    rows = read_jsonl(base_manifest)
    known_ids = {row["sample_id"] for row in rows}
    captures = sorted(Path(path).resolve() for path in captures)
    if not captures:
        raise RuntimeError("no background captures matched")
    if test_first < 0 or test_first > len(captures):
        raise ValueError("test_first must be between zero and capture count")
    if validation_last < 0 or validation_last > len(captures):
        raise ValueError("validation_last must be between zero and capture count")
    if test_first + validation_last > len(captures):
        raise ValueError("test and validation capture counts overlap")

    appended = []
    for index, image_path in enumerate(captures):
        if not image_path.is_file():
            raise RuntimeError("capture does not exist: %s" % image_path)
        sample_id = image_path.stem
        if sample_id in known_ids:
            raise RuntimeError("duplicate sample_id: %s" % sample_id)
        if index < test_first:
            split, group_id = "test", test_group
        elif validation_last and index >= len(captures) - validation_last:
            split, group_id = "validation", validation_group
        else:
            split, group_id = "train", train_group
        row = {
            "sample_id": sample_id,
            "image": image_path.as_posix(),
            "label_file": None,
            "group_field": "capture_batch",
            "group_id": group_id,
            "shape_id": "none",
            "floor_id": floor_id,
            "position_id": "empty",
            "rotation": "none",
            "partial": "none",
            "lighting": lighting,
            "review_status": "accepted",
            "split": split,
            "objects": [],
        }
        rows.append(row)
        appended.append(row)
        known_ids.add(sample_id)

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")

    summary = {
        "base_manifest": base_manifest.resolve().as_posix(),
        "output_manifest": output.resolve().as_posix(),
        "base_samples": len(rows) - len(appended),
        "background_captures": len(appended),
        "background_split_counts": dict(Counter(
            row["split"] for row in appended)),
        "background_groups": sorted({row["group_id"] for row in appended}),
        "source_images_modified": False,
    }
    summary_path = output.with_name(output.stem + "_background_summary.json")
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base_manifest")
    parser.add_argument("capture_dir")
    parser.add_argument("--glob", default="*.jpg")
    parser.add_argument(
        "--include-list",
        help="UTF-8 file containing one capture filename per line")
    parser.add_argument("--output", required=True)
    parser.add_argument("--test-first", type=int, default=0)
    parser.add_argument("--validation-last", type=int, default=0)
    parser.add_argument("--train-group", default="background_capture_train")
    parser.add_argument("--test-group", default="background_capture_test")
    parser.add_argument(
        "--validation-group", default="background_capture_validation")
    parser.add_argument("--lighting")
    parser.add_argument("--floor-id")
    args = parser.parse_args()

    capture_dir = Path(args.capture_dir).resolve()
    if args.include_list:
        names = [
            line.strip()
            for line in Path(args.include_list).read_text(
                encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        captures = [capture_dir / name for name in names]
    else:
        captures = capture_dir.glob(args.glob)
    summary = append_background(
        Path(args.base_manifest).resolve(),
        captures,
        Path(args.output).resolve(),
        args.test_first,
        args.validation_last,
        args.train_group,
        args.test_group,
        args.validation_group,
        args.lighting,
        args.floor_id,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
