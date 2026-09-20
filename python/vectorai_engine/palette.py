"""Deterministic OKLab palette hypotheses for flat multicolor graphics."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from .errors import EngineError, EngineFailure, ErrorCode, Stage
from .normalize import NormalizedImage
from .reliability import ReliabilityMap


@dataclass(frozen=True, slots=True)
class PaletteConfig:
    minimum_colors: int = 2
    maximum_colors: int = 12
    maximum_iterations: int = 32
    convergence_epsilon: float = 1.0e-7
    minimum_active_alpha: float = 0.05
    minimum_cluster_weight: float = 1.0e-4


@dataclass(frozen=True, slots=True)
class PaletteColor:
    rgb_srgb: tuple[float, float, float]
    oklab: tuple[float, float, float]
    weight: float


@dataclass(frozen=True, slots=True)
class PaletteHypothesis:
    color_count: int
    colors: tuple[PaletteColor, ...]
    labels: NDArray[np.int16]
    weighted_sse: float
    model_score: float


@dataclass(frozen=True, slots=True)
class PaletteResult:
    selected: PaletteHypothesis
    hypotheses: tuple[PaletteHypothesis, ...]
    active_pixel_count: int


def _as_float(
    value: float | int | np.float16 | np.float32 | np.float64,
    context: str,
) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as error:
        raise EngineFailure(
            EngineError(
                ErrorCode.INTERNAL_INVARIANT_VIOLATION,
                Stage.PALETTE,
                f"cannot convert {context}: {error}",
            )
        ) from error
    if not math.isfinite(result):
        raise EngineFailure(
            EngineError(
                ErrorCode.INTERNAL_INVARIANT_VIOLATION,
                Stage.PALETTE,
                f"{context} is not finite",
            )
        )
    return result


def _argmax(values: NDArray[np.float64], context: str) -> int:
    try:
        return int(np.argmax(values))
    except (TypeError, ValueError, FloatingPointError, OverflowError) as error:
        raise EngineFailure(
            EngineError(
                ErrorCode.INTERNAL_INVARIANT_VIOLATION,
                Stage.PALETTE,
                f"cannot select {context}: {error}",
            )
        ) from error


def _validate_config(config: PaletteConfig) -> None:
    if (
        config.minimum_colors < 1
        or config.maximum_colors < config.minimum_colors
        or config.maximum_colors > 12
        or config.maximum_iterations < 1
        or config.convergence_epsilon <= 0.0
        or not 0.0 <= config.minimum_active_alpha <= 1.0
        or config.minimum_cluster_weight <= 0.0
    ):
        raise EngineFailure(
            EngineError(
                ErrorCode.RESOURCE_LIMIT,
                Stage.PALETTE,
                "palette configuration is outside supported bounds",
            )
        )


def _active_samples(
    image: NormalizedImage,
    reliability: ReliabilityMap | None,
    config: PaletteConfig,
) -> tuple[NDArray[np.float64], NDArray[np.float64], NDArray[np.float64], NDArray[np.bool_]]:
    alpha = image.rgba_srgb[..., 3].astype(np.float64, copy=False)
    has_transparency = bool(np.any(alpha < 1.0 - 1.0e-6))
    active = alpha >= config.minimum_active_alpha if has_transparency else np.ones_like(alpha, bool)
    if not np.any(active):
        raise EngineFailure(
            EngineError(
                ErrorCode.PALETTE_AMBIGUOUS,
                Stage.PALETTE,
                "image has no active pixels for palette estimation",
            )
        )
    lab = image.oklab.astype(np.float64, copy=False)[active]
    rgb = image.rgba_srgb[..., :3].astype(np.float64, copy=False)[active]
    weights = np.maximum(alpha[active], 1.0e-6)
    if reliability is not None:
        if reliability.confidence.shape != alpha.shape:
            raise EngineFailure(
                EngineError(
                    ErrorCode.INTERNAL_INVARIANT_VIOLATION,
                    Stage.PALETTE,
                    "reliability dimensions do not match normalized image",
                )
            )
        weights *= 0.1 + 0.9 * reliability.confidence.astype(np.float64, copy=False)[active]
    return lab, rgb, weights, active


def _initialize_centers(
    samples: NDArray[np.float64], weights: NDArray[np.float64], count: int
) -> NDArray[np.float64]:
    weighted_mean = np.average(samples, axis=0, weights=weights)
    distance = np.sum((samples - weighted_mean) ** 2, axis=1)
    first = _argmax(distance * weights, "first palette center")
    indices = [first]
    minimum_distance = np.sum((samples - samples[first]) ** 2, axis=1)
    while len(indices) < count:
        score = minimum_distance * weights
        score[np.asarray(indices, dtype=np.int64)] = -1.0
        selected = _argmax(score, "next palette center")
        if score[selected] <= 0.0:
            break
        indices.append(selected)
        candidate_distance = np.sum((samples - samples[selected]) ** 2, axis=1)
        minimum_distance = np.minimum(minimum_distance, candidate_distance)
    if len(indices) != count:
        raise EngineFailure(
            EngineError(
                ErrorCode.PALETTE_AMBIGUOUS,
                Stage.PALETTE,
                "requested palette exceeds distinct color support",
            )
        )
    return samples[np.asarray(indices, dtype=np.int64)].copy()


def _fit_hypothesis(
    samples: NDArray[np.float64],
    rgb_samples: NDArray[np.float64],
    weights: NDArray[np.float64],
    active: NDArray[np.bool_],
    color_count: int,
    config: PaletteConfig,
) -> PaletteHypothesis:
    centers = _initialize_centers(samples, weights, color_count)
    labels = np.zeros(samples.shape[0], dtype=np.int16)
    for _ in range(config.maximum_iterations):
        squared = np.sum((samples[:, None, :] - centers[None, :, :]) ** 2, axis=2)
        labels = np.argmin(squared, axis=1).astype(np.int16)
        updated = centers.copy()
        for cluster in range(color_count):
            members = labels == cluster
            if not np.any(members):
                residual = squared[np.arange(samples.shape[0]), labels] * weights
                replacement = _argmax(residual, "empty palette cluster replacement")
                updated[cluster] = samples[replacement]
                continue
            updated[cluster] = np.average(samples[members], axis=0, weights=weights[members])
        movement = _as_float(np.max(np.abs(updated - centers)), "palette movement")
        centers = updated
        if movement <= config.convergence_epsilon:
            break

    squared = np.sum((samples[:, None, :] - centers[None, :, :]) ** 2, axis=2)
    labels = np.argmin(squared, axis=1).astype(np.int16)
    cluster_weights = np.asarray(
        [np.sum(weights[labels == cluster]) for cluster in range(color_count)],
        dtype=np.float64,
    )
    total_weight = _as_float(np.sum(cluster_weights), "total palette weight")
    if np.any(cluster_weights / total_weight < config.minimum_cluster_weight):
        raise EngineFailure(
            EngineError(
                ErrorCode.PALETTE_AMBIGUOUS,
                Stage.PALETTE,
                "palette contains an unsupported near-empty cluster",
            )
        )

    order = sorted(
        range(color_count),
        key=lambda cluster: (
            _as_float(centers[cluster, 0], "palette L"),
            _as_float(centers[cluster, 1], "palette a"),
            _as_float(centers[cluster, 2], "palette b"),
            cluster,
        ),
    )
    remap = np.empty(color_count, dtype=np.int16)
    for new_index, old_index in enumerate(order):
        remap[old_index] = new_index
    labels = remap[labels]
    centers = centers[np.asarray(order, dtype=np.int64)]
    cluster_weights = cluster_weights[np.asarray(order, dtype=np.int64)]

    colors: list[PaletteColor] = []
    for cluster in range(color_count):
        members = labels == cluster
        rgb_center = np.average(rgb_samples[members], axis=0, weights=weights[members])
        colors.append(
            PaletteColor(
                rgb_srgb=(
                    _as_float(rgb_center[0], "palette RGB"),
                    _as_float(rgb_center[1], "palette RGB"),
                    _as_float(rgb_center[2], "palette RGB"),
                ),
                oklab=(
                    _as_float(centers[cluster, 0], "palette OKLab"),
                    _as_float(centers[cluster, 1], "palette OKLab"),
                    _as_float(centers[cluster, 2], "palette OKLab"),
                ),
                weight=_as_float(cluster_weights[cluster] / total_weight, "palette weight"),
            )
        )

    canonical_squared = np.sum((samples - centers[labels]) ** 2, axis=1)
    weighted_sse = _as_float(np.sum(canonical_squared * weights), "palette SSE")
    effective_samples = max(_as_float(np.sum(weights), "effective samples"), 1.0)
    variance = max(weighted_sse / effective_samples, 1.0e-12)
    model_score = effective_samples * math.log(variance) + 3.0 * color_count * math.log(
        effective_samples
    )
    label_image = np.full(active.shape, -1, dtype=np.int16)
    label_image[active] = labels
    label_image.setflags(write=False)
    return PaletteHypothesis(
        color_count=color_count,
        colors=tuple(colors),
        labels=label_image,
        weighted_sse=weighted_sse,
        model_score=model_score,
    )


def generate_palette_hypotheses(
    image: NormalizedImage,
    reliability: ReliabilityMap | None = None,
    config: PaletteConfig | None = None,
) -> PaletteResult:
    config = config or PaletteConfig()
    _validate_config(config)
    samples, rgb, weights, active = _active_samples(image, reliability, config)
    quantized = np.round(samples, decimals=6)
    try:
        distinct_count = int(np.unique(quantized, axis=0).shape[0])
    except (TypeError, ValueError, FloatingPointError, OverflowError) as error:
        raise EngineFailure(
            EngineError(
                ErrorCode.INTERNAL_INVARIANT_VIOLATION,
                Stage.PALETTE,
                f"cannot count distinct palette samples: {error}",
            )
        ) from error
    maximum = min(config.maximum_colors, distinct_count)
    minimum = min(config.minimum_colors, maximum)
    if maximum < 1:
        raise EngineFailure(
            EngineError(
                ErrorCode.PALETTE_AMBIGUOUS,
                Stage.PALETTE,
                "image has no distinct colors",
            )
        )
    hypotheses: list[PaletteHypothesis] = []
    for color_count in range(minimum, maximum + 1):
        try:
            hypotheses.append(_fit_hypothesis(samples, rgb, weights, active, color_count, config))
        except EngineFailure as failure:
            if failure.error.code is not ErrorCode.PALETTE_AMBIGUOUS:
                raise
    if not hypotheses:
        raise EngineFailure(
            EngineError(
                ErrorCode.PALETTE_AMBIGUOUS,
                Stage.PALETTE,
                "no feasible palette hypothesis",
            )
        )
    hypotheses.sort(key=lambda item: (item.model_score, item.color_count))
    try:
        active_pixel_count = int(np.count_nonzero(active))
    except (TypeError, ValueError, OverflowError) as error:
        raise EngineFailure(
            EngineError(
                ErrorCode.INTERNAL_INVARIANT_VIOLATION,
                Stage.PALETTE,
                f"cannot count active palette samples: {error}",
            )
        ) from error
    return PaletteResult(
        selected=hypotheses[0],
        hypotheses=tuple(hypotheses),
        active_pixel_count=active_pixel_count,
    )


def symmetric_palette_error(
    predicted: tuple[PaletteColor, ...], expected_rgb: tuple[tuple[float, float, float], ...]
) -> float:
    if not predicted or not expected_rgb:
        raise ValueError("predicted and expected palettes must be non-empty")
    predicted_rgb = np.asarray([color.rgb_srgb for color in predicted], dtype=np.float64)
    expected = np.asarray(expected_rgb, dtype=np.float64)
    if (
        predicted_rgb.ndim != 2
        or expected.ndim != 2
        or predicted_rgb.shape[1] != 3
        or expected.shape[1] != 3
    ):
        raise ValueError("palette colors must be RGB triples")
    distances = np.sqrt(np.sum((predicted_rgb[:, None, :] - expected[None, :, :]) ** 2, axis=2))
    try:
        forward = float(np.mean(np.min(distances, axis=1)))
        backward = float(np.mean(np.min(distances, axis=0)))
    except (TypeError, ValueError, FloatingPointError) as error:
        raise ValueError(f"cannot aggregate palette error: {error}") from error
    return 0.5 * (forward + backward)
