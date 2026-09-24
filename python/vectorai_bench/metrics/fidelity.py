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


@dataclass(frozen=True, slots=True)
class PreparedRGBA:
    premultiplied_linear_rgb: NDArray[np.float64]
    alpha: NDArray[np.float64]


def srgb_to_linear(values: NDArray[np.float64]) -> NDArray[np.float64]:
    return np.where(
        values <= 0.04045,
        values / 12.92,
        ((values + 0.055) / 1.055) ** 2.4,
    )


_SRGB_LINEAR_LUT = srgb_to_linear(np.arange(256, dtype=np.float64) / 255.0)


def _validate_shape(array: NDArray[np.generic]) -> None:
    if array.ndim != 3 or array.shape[2] != 4:
        raise ValueError("RGBA image must have shape (height, width, 4)")
    pixel_count = array.shape[0] * array.shape[1]
    if pixel_count < 1 or pixel_count > MAX_IMAGE_PIXELS:
        raise ValueError(f"RGBA image pixel count must be in [1, {MAX_IMAGE_PIXELS}]")


def prepare_rgba(
    values: NDArray[np.uint8] | NDArray[np.float64],
) -> PreparedRGBA:
    array = np.asarray(values)
    _validate_shape(array)
    if array.dtype == np.uint8:
        integer = array.astype(np.uint8, copy=False)
        alpha = integer[..., 3:4].astype(np.float64) / 255.0
        linear_rgb = _SRGB_LINEAR_LUT[integer[..., :3]]
        np.multiply(linear_rgb, alpha, out=linear_rgb)
        return PreparedRGBA(linear_rgb, alpha)
    if not np.isfinite(array).all():
        raise ValueError("RGBA values must be finite")
    numeric = array.astype(np.float64, copy=False)
    try:
        minimum = float(np.min(numeric))
        maximum = float(np.max(numeric))
    except (TypeError, ValueError, FloatingPointError) as error:
        raise ValueError(f"cannot inspect RGBA range: {error}") from error
    if minimum < 0.0 or maximum > 1.0:
        raise ValueError("floating RGBA values must be in [0, 1]")
    alpha = numeric[..., 3:4]
    return PreparedRGBA(srgb_to_linear(numeric[..., :3]) * alpha, alpha)


def premultiplied_rgba_rmse_prepared(
    reference: PreparedRGBA,
    predicted: PreparedRGBA,
) -> float:
    if reference.alpha.shape != predicted.alpha.shape:
        raise ValueError("reference and predicted RGBA shapes must match")
    try:
        rgb_delta = reference.premultiplied_linear_rgb - predicted.premultiplied_linear_rgb
        alpha_delta = reference.alpha - predicted.alpha
        np.square(rgb_delta, out=rgb_delta)
        np.square(alpha_delta, out=alpha_delta)
        squared_error = np.sum(rgb_delta) + np.sum(alpha_delta)
        return float(np.sqrt(squared_error / (4 * reference.alpha.size)))
    except (TypeError, ValueError, FloatingPointError) as error:
        raise ValueError(f"cannot aggregate RGBA RMSE: {error}") from error


def compare_prepared_rgba(
    reference: PreparedRGBA,
    predicted: PreparedRGBA,
) -> FidelityMetrics:
    if reference.alpha.shape != predicted.alpha.shape:
        raise ValueError("reference and predicted RGBA shapes must match")
    rgb_error = np.abs(reference.premultiplied_linear_rgb - predicted.premultiplied_linear_rgb)
    alpha_error = np.abs(reference.alpha - predicted.alpha)
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


def compare_rgba(
    reference: NDArray[np.uint8] | NDArray[np.float64],
    predicted: NDArray[np.uint8] | NDArray[np.float64],
) -> FidelityMetrics:
    return compare_prepared_rgba(prepare_rgba(reference), prepare_rgba(predicted))
