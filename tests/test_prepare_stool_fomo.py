import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "laptop"))

import prepare_stool_fomo as prep  # noqa: E402


def make_session(root):
    session = root / "datasets" / "stool" / "session"
    for folder in ("images", "labels", "labels_ai"):
        (session / folder).mkdir(parents=True, exist_ok=True)
    records = []
    for index, shape in enumerate(("S01", "S02", "S03"), 1):
        sample_id = "sample%d" % index
        (session / "images" / (sample_id + ".jpg")).write_bytes(b"jpeg")
        for folder in ("labels", "labels_ai"):
            (session / folder / (sample_id + ".txt")).write_text(
                "0 0.500000 0.500000 0.200000 0.200000\n", encoding="utf-8")
        records.append({
            "sample_id": sample_id,
            "image": "images/%s.jpg" % sample_id,
            "shape_id": shape,
            "expected_instances": 1,
            "segmentation_review_status": "pending",
        })
    (session / "metadata.jsonl").write_text(
        "".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")
    return session


def test_group_split_and_smoke_pending_gate(tmp_path):
    session = make_session(tmp_path)
    output = tmp_path / "out"
    manifest, summary = prep.make_manifest(session, output, allow_pending=True)
    rows = [
        json.loads(line)
        for line in manifest.read_text(encoding="utf-8").splitlines()
    ]
    split_by_shape = {row["shape_id"]: row["split"] for row in rows}
    assert split_by_shape == {"S01": "train", "S02": "validation", "S03": "test"}
    assert summary["smoke_only"] is True
    assert summary["inference_folders_touched"] == 0


def test_rejects_inference_folder(tmp_path):
    session = make_session(tmp_path)
    inference = tmp_path / "datasets" / "stool" / "checking" / "inference_1"
    inference.parent.mkdir(parents=True)
    session.rename(inference)
    try:
        prep.make_manifest(inference, tmp_path / "out", allow_pending=True)
    except RuntimeError as error:
        assert "checking/inference" in str(error)
    else:
        raise AssertionError("inference folder was accepted")


def test_manifest_maps_multiple_configured_yolo_classes(tmp_path):
    label = tmp_path / "labels.txt"
    label.write_text(
        "0 0.25 0.25 0.1 0.1\n1 0.75 0.75 0.2 0.2\n", encoding="utf-8")
    boxes = prep.read_yolo_boxes(label, ("background", "stool", "urine"))
    assert [(box["class_id"], box["label"]) for box in boxes] == [
        (1, "stool"), (2, "urine")]


def test_manifest_group_field_is_configurable(tmp_path):
    session = make_session(tmp_path)
    metadata_path = session / "metadata.jsonl"
    records = [json.loads(line) for line in metadata_path.read_text().splitlines()]
    for index, record in enumerate(records, 1):
        record["specimen_id"] = "G%d" % index
    metadata_path.write_text(
        "".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")
    manifest, summary = prep.make_manifest(
        session, tmp_path / "out", allow_pending=True,
        group_field="specimen_id")
    rows = [json.loads(line) for line in manifest.read_text(
        encoding="utf-8").splitlines()]
    assert summary["group_field"] == "specimen_id"
    assert {row["group_id"] for row in rows} == {"G1", "G2", "G3"}
