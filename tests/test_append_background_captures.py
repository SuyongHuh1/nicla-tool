import json
from pathlib import Path
import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "laptop"))
import append_background_captures as module  # noqa: E402


def test_append_background_keeps_source_and_reserves_first_batch(tmp_path):
    source = tmp_path / "base.jsonl"
    base_row = {
        "sample_id": "positive_1",
        "image": "positive.jpg",
        "split": "validation",
        "objects": [{"class_id": 1, "bbox_yolo": [0.5, 0.5, 0.2, 0.2]}],
    }
    source.write_text(json.dumps(base_row) + "\n", encoding="utf-8")
    original = source.read_bytes()
    captures = []
    for name in (
            "negative_01.jpg", "negative_02.jpg", "negative_03.jpg",
            "negative_04.jpg"):
        path = tmp_path / name
        path.write_bytes(b"jpeg-placeholder")
        captures.append(path)

    output = tmp_path / "extended.jsonl"
    summary = module.append_background(
        source, captures, output, test_first=1, validation_last=1,
        lighting="low_light")
    rows = module.read_jsonl(output)

    assert source.read_bytes() == original
    assert summary["background_split_counts"] == {
        "test": 1, "train": 2, "validation": 1}
    assert rows[1]["split"] == "test"
    assert rows[2]["split"] == "train"
    assert rows[4]["split"] == "validation"
    assert rows[1]["objects"] == []
    assert rows[1]["lighting"] == "low_light"
    assert rows[1]["group_id"] != rows[2]["group_id"]
    assert rows[2]["group_id"] != rows[4]["group_id"]


def test_cli_style_include_list_preserves_explicit_selection(tmp_path):
    capture_dir = tmp_path / "captures"
    capture_dir.mkdir()
    for name in ("keep_a.jpg", "drop.jpg", "keep_b.jpg"):
        (capture_dir / name).write_bytes(b"jpeg-placeholder")
    names = ["keep_a.jpg", "keep_b.jpg"]
    captures = [capture_dir / name for name in names]
    source = tmp_path / "base.jsonl"
    source.write_text(
        json.dumps({
            "sample_id": "positive_1", "image": "positive.jpg",
            "split": "test", "objects": []}) + "\n",
        encoding="utf-8",
    )

    output = tmp_path / "selected.jsonl"
    module.append_background(source, captures, output)
    selected = [row["sample_id"] for row in module.read_jsonl(output)[1:]]

    assert selected == ["keep_a", "keep_b"]
    assert "drop" not in selected
