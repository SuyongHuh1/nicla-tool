"""Export viewer recordings into a review-first FOMO dataset workspace.

Examples:
  py laptop\\prepare_fomo_dataset.py recordings\\20261108_stool --split train --blob-class stool
  py laptop\\prepare_fomo_dataset.py recordings\\session1 recordings\\session2 --split auto --every 5

The generated manifest is deliberately not a final training annotation.  Every
auto-proposed box has ``reviewed: false`` and must be checked in Edge Impulse or
another annotation tool before training.  Splits are assigned per recording,
never per neighbouring frame, to avoid train/test leakage.
"""

import argparse
import hashlib
import json
import os
import shutil
import sys


CLASSES = ("stool", "urine")
SPLITS = ("train", "validation", "test")


def recording_split(name):
    bucket = int(hashlib.sha1(name.encode("utf-8")).hexdigest()[:8], 16) % 100
    return "train" if bucket < 70 else "validation" if bucket < 85 else "test"


def clamp_bbox(bbox, width, height):
    x, y, w, h = [int(v) for v in bbox]
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(width, x + max(0, w)), min(height, y + max(0, h))
    return [x0, y0, x1 - x0, y1 - y0] if x1 > x0 and y1 > y0 else None


def proposals(header, blob_class=None, include_unrefined=False):
    width, height = int(header.get("w", 0)), int(header.get("h", 0))
    objects, skipped_unrefined = [], 0
    for det in header.get("det", []) or []:
        label = det.get("cls")
        if label == "blob":
            label = blob_class
        if label not in CLASSES or "bbox" not in det:
            continue
        if det.get("refined") is False and not include_unrefined:
            skipped_unrefined += 1
            continue
        bbox = clamp_bbox(det["bbox"], width, height)
        if not bbox:
            continue
        objects.append({"label": label, "bbox": bbox,
                        "proposal_source": det.get("region_source", det.get("source", "unknown")),
                        "confidence": det.get("conf"), "reviewed": False})
    return objects, skipped_unrefined


def read_metadata(recording):
    path = os.path.join(recording, "meta.jsonl")
    if not os.path.isfile(path):
        raise FileNotFoundError("missing recording metadata: %s" % path)
    with open(path, encoding="utf-8") as f:
        for line_number, line in enumerate(f, 1):
            if line.strip():
                try:
                    yield json.loads(line)
                except json.JSONDecodeError as e:
                    raise ValueError("%s:%d: %s" % (path, line_number, e)) from e


def read_session_metadata(recording):
    path = os.path.join(recording, "session.json")
    if not os.path.isfile(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def export_recordings(recordings, out_dir, split="auto", every=5, blob_class=None,
                      include_empty=True, include_unrefined=False, append=False):
    if split != "auto" and split not in SPLITS:
        raise ValueError("invalid split: %s" % split)
    if every < 1:
        raise ValueError("every must be >= 1")
    os.makedirs(out_dir, exist_ok=True)
    manifest_path = os.path.join(out_dir, "manifest.jsonl")
    if os.path.exists(manifest_path) and not append:
        raise FileExistsError("%s exists; use --append or choose another --out" % manifest_path)

    stats = {"frames": 0, "stool": 0, "urine": 0, "empty": 0,
             "skipped_unrefined": 0, "skipped_missing": 0}
    mode = "a" if append else "w"
    with open(manifest_path, mode, encoding="utf-8") as manifest:
        for recording in recordings:
            session = os.path.basename(os.path.normpath(recording))
            session_meta = read_session_metadata(recording)
            session_split = recording_split(session) if split == "auto" else split
            image_dir = os.path.join(out_dir, "images", session_split)
            os.makedirs(image_dir, exist_ok=True)
            for index, row in enumerate(read_metadata(recording)):
                if index % every:
                    continue
                header = row.get("hdr", {})
                objects, unrefined = proposals(header, blob_class, include_unrefined)
                stats["skipped_unrefined"] += unrefined
                if unrefined and not include_unrefined:
                    continue  # never turn a known unrefined object into a negative sample
                if not objects and not include_empty:
                    continue
                source_name = row.get("file")
                source = os.path.join(recording, "frames", source_name or "")
                if not source_name or not os.path.isfile(source):
                    stats["skipped_missing"] += 1
                    continue
                target_name = "%s_%s" % (session, source_name)
                target = os.path.join(image_dir, target_name)
                shutil.copy2(source, target)
                item = {"file": os.path.relpath(target, out_dir).replace("\\", "/"),
                        "split": session_split, "source_recording": session,
                        "source_frame": source_name, "width": header.get("w"),
                        "height": header.get("h"), "detector": header.get("detector"),
                        "illum": header.get("illum"), "led": header.get("led"),
                        "session_meta": session_meta, "objects": objects,
                        "review_required": True}
                manifest.write(json.dumps(item, ensure_ascii=False) + "\n")
                stats["frames"] += 1
                if not objects:
                    stats["empty"] += 1
                for obj in objects:
                    stats[obj["label"]] += 1
    return manifest_path, stats


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("recording", nargs="+", help="viewer recording folder(s)")
    ap.add_argument("--out", default=os.path.join("datasets", "fomo"))
    ap.add_argument("--split", choices=("auto",) + SPLITS, default="auto",
                    help="auto assigns whole recordings 70/15/15")
    ap.add_argument("--every", type=int, default=5, help="keep every Nth frame")
    ap.add_argument("--blob-class", choices=CLASSES,
                    help="map old phase-1 cls=blob proposals to this class")
    ap.add_argument("--exclude-empty", action="store_true", help="omit background-only frames")
    ap.add_argument("--include-unrefined", action="store_true",
                    help="export FOMO-centred ROI boxes that do not have region refinement")
    ap.add_argument("--append", action="store_true")
    a = ap.parse_args(argv)
    try:
        path, stats = export_recordings(a.recording, a.out, a.split, a.every, a.blob_class,
                                        not a.exclude_empty, a.include_unrefined, a.append)
    except (OSError, ValueError) as e:
        sys.exit(str(e))
    print(json.dumps(stats, indent=2))
    print("review proposals before training -> %s" % path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
