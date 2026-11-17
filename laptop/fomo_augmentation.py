"""Leakage-safe, on-the-fly augmentation for the FOMO training split.

Only the training ``tf.data`` pipeline calls this module.  Source images,
labels, validation, test, and checking/inference folders remain unchanged.
Geometric shifts are quantized to whole FOMO cells so image and heatmap labels
stay exactly aligned.
"""

import json
from pathlib import Path


PRESETS = {
    "none": {
        "horizontal_flip_probability": 0.0,
        "max_shift_cells": 0,
        "brightness_delta": 0.0,
        "contrast_range": [1.0, 1.0],
        "saturation_range": [1.0, 1.0],
        "hue_delta": 0.0,
        "shadow_probability": 0.0,
        "shadow_strength_range": [0.18, 0.42],
        "noise_stddev": 0.0,
        "blur_probability": 0.0,
    },
    "mild": {
        "horizontal_flip_probability": 0.5,
        "max_shift_cells": 0,
        "brightness_delta": 14.0,
        "contrast_range": [0.90, 1.10],
        "saturation_range": [0.92, 1.08],
        "hue_delta": 0.015,
        "shadow_probability": 0.20,
        "shadow_strength_range": [0.12, 0.28],
        "noise_stddev": 2.0,
        "blur_probability": 0.08,
    },
    "default": {
        "horizontal_flip_probability": 0.5,
        "max_shift_cells": 1,
        "brightness_delta": 22.0,
        "contrast_range": [0.82, 1.18],
        "saturation_range": [0.88, 1.12],
        "hue_delta": 0.025,
        "shadow_probability": 0.35,
        "shadow_strength_range": [0.18, 0.42],
        "noise_stddev": 3.0,
        "blur_probability": 0.12,
    },
}


PROBABILITY_KEYS = (
    "horizontal_flip_probability", "shadow_probability", "blur_probability")
RANGE_KEYS = ("contrast_range", "saturation_range", "shadow_strength_range")


def validate_config(config):
    unknown = sorted(set(config) - set(PRESETS["default"]) - {"preset"})
    if unknown:
        raise ValueError("unknown augmentation keys: %s" % ", ".join(unknown))
    for key in PROBABILITY_KEYS:
        value = float(config[key])
        if value < 0.0 or value > 1.0:
            raise ValueError("%s must be in 0..1" % key)
    for key in RANGE_KEYS:
        values = config[key]
        if len(values) != 2 or float(values[0]) > float(values[1]):
            raise ValueError("%s must be [minimum, maximum]" % key)
    shift = int(config["max_shift_cells"])
    if shift < 0 or shift > 3:
        raise ValueError("max_shift_cells must be in 0..3")
    if float(config["brightness_delta"]) < 0:
        raise ValueError("brightness_delta must be non-negative")
    if float(config["hue_delta"]) < 0 or float(config["hue_delta"]) > 0.2:
        raise ValueError("hue_delta must be in 0..0.2")
    if float(config["noise_stddev"]) < 0:
        raise ValueError("noise_stddev must be non-negative")
    return config


def resolve_config(preset="default", config_path=None):
    overrides = {}
    if config_path:
        overrides = json.loads(Path(config_path).read_text(encoding="utf-8"))
        preset = overrides.pop("preset", preset)
    if preset not in PRESETS:
        raise ValueError("unknown augmentation preset: %s" % preset)
    config = dict(PRESETS[preset])
    config.update(overrides)
    config["preset"] = preset
    validate_config(config)
    return config


def active_transforms(config):
    active = []
    if config["horizontal_flip_probability"]:
        active.append("horizontal_flip")
    if config["max_shift_cells"]:
        active.append("whole_fomo_cell_shift")
    if config["brightness_delta"]:
        active.append("brightness")
    if list(config["contrast_range"]) != [1.0, 1.0]:
        active.append("contrast")
    if list(config["saturation_range"]) != [1.0, 1.0]:
        active.append("saturation")
    if config["hue_delta"]:
        active.append("hue")
    if config["shadow_probability"]:
        active.append("soft_partial_shadow")
    if config["noise_stddev"]:
        active.append("sensor_noise")
    if config["blur_probability"]:
        active.append("mild_blur")
    return active


def _shift_with_padding(tensor, dy, dx, pad, tf, image=False):
    if image:
        padded = tf.pad(tensor, [[pad, pad], [pad, pad], [0, 0]], mode="REFLECT")
        begin = [pad - dy, pad - dx, 0]
        size = [tf.shape(tensor)[0], tf.shape(tensor)[1], tf.shape(tensor)[2]]
    else:
        fill = tf.cast(1.0 if tensor.dtype.is_floating else 0, tensor.dtype)
        padded = tf.pad(tensor, [[pad, pad], [pad, pad]],
                        mode="CONSTANT", constant_values=fill)
        begin = [pad - dy, pad - dx]
        size = [tf.shape(tensor)[0], tf.shape(tensor)[1]]
    return tf.slice(padded, begin, size)


def _add_shadow(image, input_size, config, tf):
    yy, xx = tf.meshgrid(
        tf.linspace(-1.0, 1.0, input_size),
        tf.linspace(-1.0, 1.0, input_size), indexing="ij")
    angle = tf.random.uniform([], 0.0, 6.28318530718)
    offset = tf.random.uniform([], -0.7, 0.7)
    edge = tf.cos(angle) * xx + tf.sin(angle) * yy - offset
    mask = tf.sigmoid(edge * tf.random.uniform([], 5.0, 14.0))[..., None]
    lo, hi = [float(v) for v in config["shadow_strength_range"]]
    strength = tf.random.uniform([], lo, hi)
    return image * (1.0 - mask * strength)


def augment_triplet(image, target, weight, input_size, grid_size, config, tf):
    """Apply one random augmentation while preserving image/label alignment."""
    flip_probability = float(config["horizontal_flip_probability"])
    if flip_probability:
        flip = tf.random.uniform([]) < flip_probability
        image = tf.cond(flip, lambda: tf.image.flip_left_right(image), lambda: image)
        target = tf.cond(flip, lambda: tf.reverse(target, axis=[1]), lambda: target)
        weight = tf.cond(flip, lambda: tf.reverse(weight, axis=[1]), lambda: weight)

    max_shift = int(config["max_shift_cells"])
    if max_shift:
        dy = tf.random.uniform([], -max_shift, max_shift + 1, dtype=tf.int32)
        dx = tf.random.uniform([], -max_shift, max_shift + 1, dtype=tf.int32)
        cell_px = input_size // grid_size
        image = _shift_with_padding(
            image, dy * cell_px, dx * cell_px, max_shift * cell_px, tf, image=True)
        target = _shift_with_padding(target, dy, dx, max_shift, tf)
        weight = _shift_with_padding(weight, dy, dx, max_shift, tf)

    brightness = float(config["brightness_delta"])
    if brightness:
        image = tf.image.random_brightness(image, max_delta=brightness)
    contrast = [float(v) for v in config["contrast_range"]]
    if contrast != [1.0, 1.0]:
        image = tf.image.random_contrast(image, lower=contrast[0], upper=contrast[1])

    saturation = [float(v) for v in config["saturation_range"]]
    hue = float(config["hue_delta"])
    if saturation != [1.0, 1.0] or hue:
        image01 = tf.clip_by_value(image / 255.0, 0.0, 1.0)
        if saturation != [1.0, 1.0]:
            image01 = tf.image.random_saturation(
                image01, lower=saturation[0], upper=saturation[1])
        if hue:
            image01 = tf.image.random_hue(image01, max_delta=hue)
        image = image01 * 255.0

    shadow_probability = float(config["shadow_probability"])
    if shadow_probability:
        image = tf.cond(
            tf.random.uniform([]) < shadow_probability,
            lambda: _add_shadow(image, input_size, config, tf),
            lambda: image)

    noise = float(config["noise_stddev"])
    if noise:
        image = image + tf.random.normal(tf.shape(image), stddev=noise)

    blur_probability = float(config["blur_probability"])
    if blur_probability:
        image = tf.cond(
            tf.random.uniform([]) < blur_probability,
            lambda: tf.nn.avg_pool2d(
                image[None, ...], ksize=3, strides=1, padding="SAME")[0],
            lambda: image)

    return tf.clip_by_value(image, 0.0, 255.0), target, weight
