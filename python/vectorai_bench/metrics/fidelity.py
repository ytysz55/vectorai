"""Linear-light premultiplied RGBA fidelity metrics."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

METRIC_VERSION = "1.0.0"
MAX_IMAGE_PIXELS = 16_777_216


@dataclass(frozen=True, slots=True)
class FidelityMetrics:
    metric_version: str
    linear_rgb_mae: float
    alpha_mae: float
    premultiplied_rgba_rmse: float
    max_channel_error: float


def srgb_to_linear(values: NDArray[np.float64]) -> NDArray[np.float64]:
    return np.where(
        values <= 0.04045,
        values / 12.92,
        ((values + 0.055) / 1.055) ** 2.4,
    )


def _rgba(values: NDArray[np.uint8] | NDArray[np.float64]) -> NDArray[np.float64]:
    array = np.asarray(values)
    if array.ndim != 3 or array.shape[2] != 4:
        raise ValueError("RGBA image must have shape (height, width, 4)")
    pixel_count = array.shape[0] * array.shape[1]
    if pixel_count < 1 or pixel_count > MAX_IMAGE_PIXELS:
        raise ValueError(f"RGBA image pixel count must be in [1, {MAX_IMAGE_PIXELS}]")
    if not np.isfinite(array).all():
        raise ValueError("RGBA values must be finite")
    numeric = array.astype(np.float64, copy=False)
    try:
        minimum = float(np.min(numeric))
        maximum = float(np.max(numeric))
    except (TypeError, ValueError, FloatingPointError) as error:
        raise ValueError(f"cannot inspect RGBA range: {error}") from error
    if np.issubdtype(array.dtype, np.integer):
        if minimum < 0.0 or maximum > 255.0:
            raise ValueError("integer RGBA values must be in [0, 255]")
        return numeric / 255.0
    floating = numeric
    if minimum < 0.0 or maximum > 1.0:
        raise ValueError("floating RGBA values must be in [0, 1]")
    return floating


def compare_rgba(
    reference: NDArray[np.uint8] | NDArray[np.float64],
    predicted: NDArray[np.uint8] | NDArray[np.float64],
) -> FidelityMetrics:
    reference_rgba = _rgba(reference)
    predicted_rgba = _rgba(predicted)
    if reference_rgba.shape != predicted_rgba.shape:
        raise ValueError("reference and predicted RGBA shapes must match")

    reference_alpha = reference_rgba[..., 3:4]
    predicted_alpha = predicted_rgba[..., 3:4]
    reference_rgb = srgb_to_linear(reference_rgba[..., :3]) * reference_alpha
    predicted_rgb = srgb_to_linear(predicted_rgba[..., :3]) * predicted_alpha

    rgb_error = np.abs(reference_rgb - predicted_rgb)
    alpha_error = np.abs(reference_alpha - predicted_alpha)
    rgba_error = np.concatenate((rgb_error, alpha_error), axis=2)
    try:
        rgb_mae = float(np.mean(rgb_error))
        alpha_mae = float(np.mean(alpha_error))
        rgba_rmse = float(np.sqrt(np.mean(rgba_error * rgba_error)))
        max_error = float(np.max(rgba_error))
    except (TypeError, ValueError, FloatingPointError) as error:
        raise ValueError(f"cannot aggregate RGBA error: {error}") from error
    return FidelityMetrics(
        metric_version=METRIC_VERSION,
        linear_rgb_mae=rgb_mae,
        alpha_mae=alpha_mae,
        premultiplied_rgba_rmse=rgba_rmse,
        max_channel_error=max_error,
    )
