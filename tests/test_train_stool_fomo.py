from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "laptop"))

import train_stool_fomo as train  # noqa: E402
import fomo_augmentation  # noqa: E402


def test_target_supports_future_stool_and_urine_classes():
    row = {"objects": [
        {"class_id": 1, "bbox_yolo": [0.25, 0.25, 0.1, 0.1]},
        {"class_id": 2, "bbox_yolo": [0.75, 0.75, 0.2, 0.2]},
    ]}
    target = train.target_for_row(row, class_count=3)
    assert target[3, 3] == 1
    assert target[9, 9] == 2


def test_target_rejects_class_outside_model_head():
    row = {"objects": [
        {"class_id": 2, "bbox_yolo": [0.5, 0.5, 0.1, 0.1]},
    ]}
    try:
        train.target_for_row(row, class_count=2)
    except RuntimeError as error:
        assert "outside model output range" in str(error)
    else:
        raise AssertionError("invalid class was accepted")


def test_default_augmentation_is_training_safe_and_no_fake_rotation():
    config = fomo_augmentation.resolve_config("default")
    active = fomo_augmentation.active_transforms(config)
    assert "whole_fomo_cell_shift" in active
    assert "soft_partial_shadow" in active
    assert "whole_frame_rotation" not in active
    assert "vertical_flip" not in active


def test_augmentation_json_can_override_without_code_changes(tmp_path):
    path = tmp_path / "augmentation.json"
    path.write_text(
        '{"preset":"mild","shadow_probability":0.0,"max_shift_cells":1}',
        encoding="utf-8")
    config = fomo_augmentation.resolve_config("default", path)
    assert config["preset"] == "mild"
    assert config["shadow_probability"] == 0.0
    assert config["max_shift_cells"] == 1


def test_invalid_augmentation_probability_is_rejected(tmp_path):
    path = tmp_path / "augmentation.json"
    path.write_text('{"blur_probability":1.5}', encoding="utf-8")
    try:
        fomo_augmentation.resolve_config("default", path)
    except ValueError as error:
        assert "blur_probability" in str(error)
    else:
        raise AssertionError("invalid augmentation probability was accepted")
