import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "laptop"))

import summarize_stool_cv as summary  # noqa: E402


def write_fold(root, test_shape, val_shape, f1):
    fold = root / ("fold_test_" + test_shape)
    validation = fold / "validation"
    validation.mkdir(parents=True)
    report = {
        "status": "PROVISIONAL",
        "selected_threshold": 0.6,
        "split_integrity": {"shapes": {
            "test": [test_shape], "validation": [val_shape]}},
        "test": {
            "samples": 10, "precision": f1, "recall": f1, "f1": f1,
            "exact_count_rate": f1, "top_within_one_cell_rate": f1,
            "false_positives_per_image": 0.0,
        },
        "test_roi_sweep": [{
            "roi_size": [112, 112],
            "bbox_coverage_at_least_90_all_gt_rate": 0.5,
        }],
    }
    (validation / "validation_report.json").write_text(json.dumps(report))
    (fold / "training_report.json").write_text(json.dumps({
        "tflite": {"bytes": 1234}, "epochs_completed": 2,
    }))


def test_load_and_aggregate_unique_test_shapes(tmp_path):
    write_fold(tmp_path, "S01", "S02", 0.8)
    write_fold(tmp_path, "S02", "S01", 0.6)
    folds = summary.load_folds(tmp_path)
    aggregate = summary.aggregate(folds)
    assert len(folds) == 2
    assert aggregate["f1"]["mean"] == 0.7
    assert aggregate["f1"]["min"] == 0.6
