import json
import os
import sys


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "laptop"))

import prepare_fomo_dataset as prep  # noqa: E402


def write_recording(root):
    recording = root / "session_wood_room"
    frames = recording / "frames"
    frames.mkdir(parents=True)
    rows = [
        {"file": "000001.jpg", "hdr": {"w": 320, "h": 240, "detector": "color_demo",
         "det": [{"cls": "blob", "bbox": [10, 20, 30, 40], "refined": True,
                  "region_source": "lab"}]}},
        {"file": "000002.jpg", "hdr": {"w": 320, "h": 240, "detector": "color_demo", "det": []}},
        {"file": "000003.jpg", "hdr": {"w": 320, "h": 240, "detector": "tinyml_roi",
         "det": [{"cls": "urine", "bbox": [50, 60, 80, 70], "refined": False,
                  "region_source": "fomo_roi"}]}},
    ]
    for row in rows:
        (frames / row["file"]).write_bytes(b"jpeg")
    with open(recording / "meta.jsonl", "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")
    with open(recording / "session.json", "w", encoding="utf-8") as f:
        json.dump({"target": "stool", "floor": "wood_a", "mount_id": "front_v1"}, f)
    return recording


def test_export_marks_proposals_unreviewed_and_skips_unrefined(tmp_path):
    recording = write_recording(tmp_path)
    out = tmp_path / "dataset"
    manifest, stats = prep.export_recordings([str(recording)], str(out), split="train",
                                             every=1, blob_class="stool")
    rows = [json.loads(line) for line in open(manifest, encoding="utf-8")]
    assert stats == {"frames": 2, "stool": 1, "urine": 0, "empty": 1,
                     "skipped_unrefined": 1, "skipped_missing": 0}
    assert rows[0]["objects"][0]["label"] == "stool"
    assert rows[0]["objects"][0]["reviewed"] is False
    assert rows[0]["session_meta"]["floor"] == "wood_a"
    assert rows[0]["session_meta"]["mount_id"] == "front_v1"
    assert rows[1]["objects"] == []

