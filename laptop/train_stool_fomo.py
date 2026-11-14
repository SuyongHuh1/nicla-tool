"""Train and int8-quantize a small FOMO-style stool-centre smoke model.

This is a pipeline validation model, not a final model.  It accepts a manifest
created by prepare_stool_fomo.py and predicts a 12x12 background/stool centroid
heatmap from a 96x96 RGB frame.
"""

import argparse
import json
from pathlib import Path
import time

import cv2
import numpy as np

import fomo_augmentation


INPUT_SIZE = 96
GRID_SIZE = 12
DEFAULT_CLASS_NAMES = ("background", "stool")


def read_manifest(path):
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def read_image(path):
    encoded = np.fromfile(str(path), dtype=np.uint8)
    image = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
    if image is None:
        raise RuntimeError("cannot decode image: %s" % path)
    image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    return cv2.resize(image, (INPUT_SIZE, INPUT_SIZE), interpolation=cv2.INTER_AREA)


def target_for_row(row, class_count):
    target = np.zeros((GRID_SIZE, GRID_SIZE), dtype=np.uint8)
    for obj in row["objects"]:
        class_id = int(obj["class_id"])
        if class_id <= 0 or class_id >= class_count:
            raise RuntimeError(
                "class_id %d is outside model output range 1..%d" % (
                    class_id, class_count - 1))
        cx, cy = obj["bbox_yolo"][:2]
        x = min(GRID_SIZE - 1, max(0, int(float(cx) * GRID_SIZE)))
        y = min(GRID_SIZE - 1, max(0, int(float(cy) * GRID_SIZE)))
        if target[y, x] not in (0, class_id):
            raise RuntimeError("two classes map to the same FOMO grid cell")
        target[y, x] = class_id
    return target


def load_split(rows, split, positive_weight, class_count):
    selected = [row for row in rows if row["split"] == split]
    images = np.stack([read_image(Path(row["image"])) for row in selected]).astype(np.float32)
    targets = np.stack([
        target_for_row(row, class_count) for row in selected
    ]).astype(np.uint8)
    weights = np.ones(targets.shape, dtype=np.float32)
    weights[targets > 0] = float(positive_weight)
    return selected, images, targets, weights


def make_dataset(images, targets, weights, batch_size, tf, training,
                 augmentation=None):
    dataset = tf.data.Dataset.from_tensor_slices((images, targets, weights))
    if training:
        dataset = dataset.shuffle(len(images), reshuffle_each_iteration=True)
        augmentation = augmentation or fomo_augmentation.resolve_config("default")

        def augment(image, target, weight):
            return fomo_augmentation.augment_triplet(
                image, target, weight, INPUT_SIZE, GRID_SIZE, augmentation, tf)

        dataset = dataset.map(augment, num_parallel_calls=tf.data.AUTOTUNE)
    return dataset.batch(batch_size).prefetch(tf.data.AUTOTUNE)


def conv_block(x, filters, stride, tf, name):
    x = tf.keras.layers.DepthwiseConv2D(
        3, strides=stride, padding="same", use_bias=True, name=name + "_dw")(x)
    x = tf.keras.layers.ReLU(max_value=6.0, name=name + "_dw_relu")(x)
    x = tf.keras.layers.Conv2D(
        filters, 1, padding="same", use_bias=True, name=name + "_pw")(x)
    return tf.keras.layers.ReLU(max_value=6.0, name=name + "_pw_relu")(x)


def build_model(tf, architecture="tiny", class_count=2):
    inputs = tf.keras.Input((INPUT_SIZE, INPUT_SIZE, 3), name="image")
    x = tf.keras.layers.Rescaling(1.0 / 127.5, offset=-1.0, name="normalize")(inputs)
    if architecture == "tiny":
        x = tf.keras.layers.Conv2D(
            12, 3, strides=2, padding="same", use_bias=True, name="stem_conv")(x)
        x = tf.keras.layers.ReLU(max_value=6.0, name="stem_relu")(x)
        x = conv_block(x, 16, 1, tf, "block1")
        x = conv_block(x, 24, 2, tf, "block2")
        x = conv_block(x, 32, 2, tf, "block3")
        x = conv_block(x, 32, 1, tf, "block4")
        model_name = "stool_fomo_tiny_smoke"
    elif architecture == "mobilenetv2_035":
        backbone = tf.keras.applications.MobileNetV2(
            input_tensor=x, include_top=False, weights=None, alpha=0.35)
        for layer in backbone.layers:
            if isinstance(layer, tf.keras.layers.BatchNormalization):
                layer.momentum = 0.9
        x = backbone.get_layer("block_5_add").output
        x = tf.keras.layers.Conv2D(
            24, 1, padding="same", activation="relu", name="fomo_adapter")(x)
        model_name = "stool_fomo_mobilenetv2_035_smoke"
    else:
        raise ValueError("unknown architecture: %s" % architecture)
    logits = tf.keras.layers.Conv2D(class_count, 1, name="fomo_logits")(x)
    outputs = tf.keras.layers.Softmax(name="fomo_softmax")(logits)
    model = tf.keras.Model(inputs, outputs, name=model_name)
    if model.output_shape != (None, GRID_SIZE, GRID_SIZE, class_count):
        raise RuntimeError("unexpected model output shape: %r" % (model.output_shape,))
    return model


def localization_metrics(model, rows, images, targets, split, class_id, class_name):
    probabilities = model.predict(images, verbose=0)[..., class_id]
    errors = []
    within_one = 0
    positives = 0
    background_confidences = []
    details = []
    for row, probability, target in zip(rows, probabilities, targets):
        pred_y, pred_x = np.unravel_index(np.argmax(probability), probability.shape)
        confidence = float(probability[pred_y, pred_x])
        positive_points = np.argwhere(target == class_id)
        if len(positive_points):
            positives += 1
            distances = [
                float(np.hypot(pred_y - int(point[0]), pred_x - int(point[1])))
                for point in positive_points
            ]
            error = min(distances)
            errors.append(error)
            within_one += int(error <= np.sqrt(2.0))
        else:
            error = None
            background_confidences.append(confidence)
        details.append({
            "sample_id": row["sample_id"],
            "group_id": row.get("group_id", row.get("shape_id", "unknown")),
            "predicted_cell_xy": [int(pred_x), int(pred_y)],
            "stool_confidence": confidence,
            "cell_error": error,
        })
    return {
        "split": split,
        "class_id": class_id,
        "class_name": class_name,
        "samples": len(rows),
        "positive_samples": positives,
        "mean_cell_error": float(np.mean(errors)) if errors else None,
        "within_one_cell_rate": float(within_one / positives) if positives else None,
        "background_max_confidence": (
            float(max(background_confidences)) if background_confidences else None),
        "details": details,
    }


def write_contact_sheet(path, rows, images, targets, model, class_id):
    probabilities = model.predict(images, verbose=0)[..., class_id]
    tile_w, tile_h = 192, 222
    columns = 6
    rows_count = int(np.ceil(len(rows) / columns))
    sheet = np.full((rows_count * tile_h, columns * tile_w, 3), 235, np.uint8)
    for index, (row, rgb, target, probability) in enumerate(
            zip(rows, images, targets, probabilities)):
        tile = cv2.cvtColor(rgb.astype(np.uint8), cv2.COLOR_RGB2BGR)
        tile = cv2.resize(tile, (tile_w, 192), interpolation=cv2.INTER_NEAREST)
        pred_y, pred_x = np.unravel_index(np.argmax(probability), probability.shape)
        px = int((pred_x + 0.5) * tile_w / GRID_SIZE)
        py = int((pred_y + 0.5) * 192 / GRID_SIZE)
        cv2.drawMarker(tile, (px, py), (0, 0, 255), cv2.MARKER_CROSS, 14, 2)
        for gt_y, gt_x in np.argwhere(target == class_id):
            gx = int((int(gt_x) + 0.5) * tile_w / GRID_SIZE)
            gy = int((int(gt_y) + 0.5) * 192 / GRID_SIZE)
            cv2.drawMarker(tile, (gx, gy), (0, 255, 0), cv2.MARKER_TILTED_CROSS, 14, 2)
        x0, y0 = (index % columns) * tile_w, (index // columns) * tile_h
        sheet[y0:y0 + 192, x0:x0 + tile_w] = tile
        group_id = row.get("group_id", row.get("shape_id", "unknown"))
        caption = "%s  %.2f" % (group_id, float(probability[pred_y, pred_x]))
        cv2.putText(sheet, caption, (x0 + 4, y0 + 211), cv2.FONT_HERSHEY_SIMPLEX,
                    0.45, (20, 20, 20), 1, cv2.LINE_AA)
    ok, encoded = cv2.imencode(".jpg", sheet, [cv2.IMWRITE_JPEG_QUALITY, 92])
    if not ok:
        raise RuntimeError("failed to encode contact sheet")
    encoded.tofile(str(path))


def convert_int8(model, representative_images, destination, tf):
    def representative_dataset():
        for image in representative_images[: min(100, len(representative_images))]:
            yield [image[None, ...].astype(np.float32)]

    # TensorFlow 2.21 + Keras 3 can fail in from_keras_model() while resolving
    # its internal call context. A concrete inference function avoids that
    # path. Freeze resource variables before calibration as well: on native
    # Windows the converter can otherwise intermittently emit READ_VARIABLE
    # nodes whose resources are not initialized by the int8 calibrator.
    inference = tf.function(
        lambda image: model(image, training=False),
        input_signature=[tf.TensorSpec(
            [1, INPUT_SIZE, INPUT_SIZE, 3], tf.float32, name="image")],
    )
    concrete = inference.get_concrete_function()
    from tensorflow.python.framework.convert_to_constants import (  # noqa: PLC0415
        convert_variables_to_constants_v2,
    )
    frozen = convert_variables_to_constants_v2(concrete)
    converter = tf.lite.TFLiteConverter.from_concrete_functions([frozen])
    converter.optimizations = [tf.lite.Optimize.DEFAULT]
    converter.representative_dataset = representative_dataset
    converter.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS_INT8]
    converter.inference_input_type = tf.uint8
    converter.inference_output_type = tf.uint8
    model_bytes = converter.convert()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(model_bytes)

    interpreter = tf.lite.Interpreter(model_content=model_bytes)
    interpreter.allocate_tensors()
    input_detail = interpreter.get_input_details()[0]
    output_detail = interpreter.get_output_details()[0]
    return {
        "bytes": len(model_bytes),
        "input_shape": input_detail["shape"].astype(int).tolist(),
        "input_dtype": str(input_detail["dtype"]),
        "input_quantization": list(input_detail["quantization"]),
        "output_shape": output_detail["shape"].astype(int).tolist(),
        "output_dtype": str(output_detail["dtype"]),
        "output_quantization": list(output_detail["quantization"]),
    }


def quantization_parity(model, model_path, images, class_id, tf):
    float_probabilities = model.predict(images, verbose=0)[..., class_id]
    interpreter = tf.lite.Interpreter(model_content=model_path.read_bytes())
    interpreter.allocate_tensors()
    input_detail = interpreter.get_input_details()[0]
    output_detail = interpreter.get_output_details()[0]
    input_scale, input_zero = input_detail["quantization"]
    output_scale, output_zero = output_detail["quantization"]
    quantized_probabilities = []
    for image in images:
        quantized = np.clip(
            np.rint(image / input_scale + input_zero), 0, 255).astype(np.uint8)
        interpreter.set_tensor(input_detail["index"], quantized[None, ...])
        interpreter.invoke()
        output = interpreter.get_tensor(output_detail["index"])[0].astype(np.float32)
        output = (output - output_zero) * output_scale
        quantized_probabilities.append(output[..., class_id])
    quantized_probabilities = np.stack(quantized_probabilities)
    float_cells = np.argmax(float_probabilities.reshape(len(images), -1), axis=1)
    quantized_cells = np.argmax(
        quantized_probabilities.reshape(len(images), -1), axis=1)
    return {
        "samples": len(images),
        "argmax_cell_agreement": float(np.mean(float_cells == quantized_cells)),
        "max_probability_abs_error": float(np.max(
            np.abs(float_probabilities - quantized_probabilities))),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest")
    parser.add_argument("--architecture", choices=("tiny", "mobilenetv2_035"),
                        default="tiny")
    parser.add_argument("--output")
    parser.add_argument("--model-out")
    parser.add_argument("--labels-out")
    parser.add_argument("--epochs", type=int, default=30)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--positive-weight", type=float, default=80.0)
    parser.add_argument("--seed", type=int, default=20261109)
    parser.add_argument(
        "--augmentation", choices=tuple(fomo_augmentation.PRESETS), default="default",
        help="training-only augmentation preset")
    parser.add_argument(
        "--augmentation-config",
        help="JSON overrides; source images and validation/test remain unchanged")
    parser.add_argument(
        "--classes", default=",".join(DEFAULT_CLASS_NAMES),
        help="ordered output labels, for example background,stool,urine")
    parser.add_argument(
        "--metric-class", default="stool",
        help="class used for localization metrics and the contact sheet")
    args = parser.parse_args()

    try:
        import tensorflow as tf
    except ImportError as error:
        raise RuntimeError(
            "TensorFlow is required; install laptop/requirements-training.txt") from error

    tf.keras.utils.set_random_seed(args.seed)
    augmentation = fomo_augmentation.resolve_config(
        args.augmentation, args.augmentation_config)
    class_names = tuple(name.strip() for name in args.classes.split(",") if name.strip())
    if len(class_names) < 2 or class_names[0] != "background":
        raise RuntimeError("classes must start with background and include an object class")
    if len(set(class_names)) != len(class_names):
        raise RuntimeError("class names must be unique")
    if args.metric_class not in class_names[1:]:
        raise RuntimeError("metric class is not an object class: %s" % args.metric_class)
    metric_class_id = class_names.index(args.metric_class)
    run_name = (
        "fomo_stool_smoke" if args.architecture == "tiny"
        else "fomo_stool_mobilenet_smoke")
    args.output = args.output or str(Path("training_runs") / run_name)
    args.model_out = args.model_out or str(Path("models") / (run_name + ".tflite"))
    args.labels_out = args.labels_out or str(
        Path("models") / (run_name + "_labels.txt"))
    rows = read_manifest(Path(args.manifest))
    data = {}
    for split in ("train", "validation", "test"):
        data[split] = load_split(
            rows, split, args.positive_weight, len(class_names))
        if not len(data[split][0]):
            raise RuntimeError("empty split: %s" % split)

    train_rows, train_x, train_y, train_w = data["train"]
    val_rows, val_x, val_y, val_w = data["validation"]
    test_rows, test_x, test_y, _test_w = data["test"]
    train_ds = make_dataset(
        train_x, train_y, train_w, args.batch_size, tf, training=True,
        augmentation=augmentation)
    val_ds = make_dataset(
        val_x, val_y, val_w, args.batch_size, tf, training=False)

    model = build_model(tf, args.architecture, len(class_names))
    model.compile(
        optimizer=tf.keras.optimizers.Adam(learning_rate=1e-3),
        loss=tf.keras.losses.SparseCategoricalCrossentropy(),
        weighted_metrics=[tf.keras.metrics.SparseCategoricalAccuracy(name="cell_accuracy")],
    )
    started = time.time()
    history = model.fit(
        train_ds,
        validation_data=val_ds,
        epochs=args.epochs,
        callbacks=[tf.keras.callbacks.EarlyStopping(
            monitor="val_loss", patience=6, restore_best_weights=True)],
        verbose=2,
    )
    elapsed = time.time() - started

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    metrics = {
        split: localization_metrics(
            model, data[split][0], data[split][1], data[split][2], split,
            metric_class_id, args.metric_class)
        for split in ("train", "validation", "test")
    }
    model_path = Path(args.model_out)
    tflite = convert_int8(model, train_x, model_path, tf)
    quantized_check = quantization_parity(
        model, model_path, test_x, metric_class_id, tf)
    labels_path = Path(args.labels_out)
    labels_path.parent.mkdir(parents=True, exist_ok=True)
    labels_path.write_text("\n".join(class_names) + "\n", encoding="utf-8")
    write_contact_sheet(
        output_dir / "test_predictions.jpg", test_rows, test_x, test_y, model,
        metric_class_id)

    report = {
        "purpose": "pipeline smoke test; not approved for deployment",
        "architecture": args.architecture,
        "manifest": str(Path(args.manifest).resolve()),
        "model": str(model_path.resolve()),
        "labels": str(labels_path.resolve()),
        "input_size": [INPUT_SIZE, INPUT_SIZE, 3],
        "output_grid": [GRID_SIZE, GRID_SIZE, len(class_names)],
        "class_names": list(class_names),
        "metric_class": args.metric_class,
        "parameters": int(model.count_params()),
        "epochs_requested": args.epochs,
        "epochs_completed": len(history.history["loss"]),
        "elapsed_seconds": elapsed,
        "history": {key: [float(value) for value in values]
                    for key, values in history.history.items()},
        "metrics": metrics,
        "tflite": tflite,
        "quantization_parity_on_test": quantized_check,
        "augmentation": {
            "scope": "train_split_only_on_the_fly",
            "config": augmentation,
            "active_transforms": fomo_augmentation.active_transforms(augmentation),
            "excluded_by_design": [
                "vertical_flip", "whole_frame_rotation", "validation_augmentation",
                "test_augmentation", "checking_inference_augmentation"
            ],
        },
    }
    (output_dir / "training_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "model": str(model_path),
        "model_bytes": tflite["bytes"],
        "output_shape": tflite["output_shape"],
        "validation": metrics["validation"],
        "test": metrics["test"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
