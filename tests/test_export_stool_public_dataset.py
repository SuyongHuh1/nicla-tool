import hashlib
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "laptop"))

import export_stool_public_dataset as exporter  # noqa: E402


def make_session(root, name, sample_id, image_bytes, shape_id):
    session = root / name
    for folder in ("images", "masks", "labels", "previews_ai"):
        (session / folder).mkdir(parents=True, exist_ok=True)
    (session / "images" / (sample_id + ".jpg")).write_bytes(image_bytes)
    (session / "masks" / (sample_id + ".png")).write_bytes(b"mask-" + image_bytes)
    (session / "labels" / (sample_id + ".txt")).write_text(
        "0 0.5 0.5 0.2 0.2\n", encoding="utf-8")
    (session / "previews_ai" / (sample_id + ".jpg")).write_bytes(b"preview")
    record = {
        "sample_id": sample_id,
        "image": "images/%s.jpg" % sample_id,
        "mask": "masks/%s.png" % sample_id,
        "label": "labels/%s.txt" % sample_id,
        "ai_preview": "previews_ai/%s.jpg" % sample_id,
        "local_debug_path": "C:/Users/example/private",
        "shape_id": shape_id,
        "expected_instances": 1,
        "segmentation_review_status": "corrected",
        "segmentation_bbox_xyxy_px": [[1, 2, 10, 12]],
    }
    (session / "metadata.jsonl").write_text(
        json.dumps(record) + "\n", encoding="utf-8")
    return session


def test_export_is_minimal_and_path_clean(tmp_path):
    train = make_session(tmp_path, "train-source", "train1", b"jpeg-train", "S01")
    evaluation = make_session(tmp_path, "eval-source", "eval1", b"jpeg-eval", "mixed")
    output = tmp_path / "public"
    seen = {}
    train_summary = exporter.export_session(train, output / "train", seen)
    eval_summary = exporter.export_session(
        evaluation, output / "evaluation" / "inference_e01", seen)
    exporter.write_checksums(output)

    assert train_summary["exported_records"] == 1
    assert eval_summary["exported_records"] == 1
    public_record = json.loads(
        (output / "train" / "metadata.jsonl").read_text().strip())
    assert public_record["image"] == "images/train1.jpg"
    assert public_record["mask"] == "masks/train1.png"
    assert public_record["label"] == "labels/train1.txt"
    assert "ai_preview" not in public_record
    assert "local_debug_path" not in public_record
    assert not (output / "train" / "previews_ai").exists()

    for line in (output / "checksums.sha256").read_text().splitlines():
        expected, relative = line.split("  ", 1)
        payload = (output / relative).read_bytes()
        assert hashlib.sha256(payload).hexdigest() == expected


def test_exact_duplicate_is_exported_once(tmp_path):
    train = make_session(tmp_path, "train-source", "train1", b"same-image", "S01")
    evaluation = make_session(tmp_path, "eval-source", "eval1", b"same-image", "mixed")
    output = tmp_path / "public"
    seen = {}
    exporter.export_session(train, output / "train", seen)
    summary = exporter.export_session(
        evaluation, output / "evaluation" / "inference_e01", seen)

    assert summary["exported_records"] == 0
    assert summary["exact_duplicates_removed"] == 1
    assert summary["duplicates"][0]["duplicate_of"] == "train1"
