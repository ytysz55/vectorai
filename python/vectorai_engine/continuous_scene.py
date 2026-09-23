"""Continuous, topology-immutable scene parameter evaluators for E5 backends."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

import numpy as np

from vectorai_bench.metrics.fidelity import srgb_to_linear

from .normalize import NormalizedImage, linear_rgb_to_oklab
from .objectives import ObjectiveContext, RawObjectiveTerms, evaluate_objective
from .optimization import (
    OptimizationResult,
    ParameterBlock,
    ParameterKind,
    SceneParameters,
    optimize_parameters,
)
from .palette import PaletteColor, PaletteResult
from .profiles import OptimizationProfile


@dataclass(frozen=True, slots=True)
class PaletteColorRefinement:
    palette: PaletteResult
    optimization: OptimizationResult
    baseline_analytic_rmse: float
    selected_analytic_rmse: float


@dataclass(frozen=True, slots=True)
class _ColorStatistics:
    weight_sum: float
    weighted_linear_sum: tuple[float, float, float]
    weighted_square_sum: tuple[float, float, float]


def _finite_float(value: object, context: str) -> float:
    try:
        result = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError(f"{context} must be numeric") from error
    if not math.isfinite(result):
        raise ValueError(f"{context} must be finite")
    return result


def _triple(values: np.ndarray) -> tuple[float, float, float]:
    flattened = values.reshape(3)
    return (
        _finite_float(flattened[0], "color statistic"),
        _finite_float(flattened[1], "color statistic"),
        _finite_float(flattened[2], "color statistic"),
    )


def _statistics(image: NormalizedImage, palette: PaletteResult) -> tuple[_ColorStatistics, ...]:
    labels = palette.selected.labels
    alpha = image.rgba_linear[..., 3].astype(np.float64, copy=False)
    linear_rgb = image.rgba_linear[..., :3].astype(np.float64, copy=False)
    result: list[_ColorStatistics] = []
    for index in range(palette.selected.color_count):
        mask = labels == index
        weights = alpha[mask] * alpha[mask]
        colors = linear_rgb[mask]
        if weights.size == 0:
            result.append(_ColorStatistics(0.0, (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)))
            continue
        result.append(
            _ColorStatistics(
                weight_sum=_finite_float(np.sum(weights), "color weight sum"),
                weighted_linear_sum=_triple(
                    np.sum(colors * weights[:, None], axis=0)
                ),
                weighted_square_sum=_triple(
                    np.sum(colors * colors * weights[:, None], axis=0)
                ),
            )
        )
    return tuple(result)


def _candidate_colors(
    parameters: SceneParameters,
    palette: PaletteResult,
    maximum_delta: float,
) -> tuple[tuple[float, float, float], ...]:
    colors: list[tuple[float, float, float]] = []
    for index, (block, values) in enumerate(
        zip(parameters.blocks, parameters.values, strict=True)
    ):
        if block.kind is not ParameterKind.COLOR:
            raise ValueError("palette refinement received a non-color parameter block")
        if block.stable_id != f"color-{index:04d}":
            raise ValueError("palette color blocks lost canonical ordering")
        initial = palette.selected.colors[index].rgb_srgb
        colors.append(
            (
                min(1.0, max(0.0, initial[0] + maximum_delta * values[0])),
                min(1.0, max(0.0, initial[1] + maximum_delta * values[1])),
                min(1.0, max(0.0, initial[2] + maximum_delta * values[2])),
            )
        )
    return tuple(colors)


def _analytic_rmse(
    colors_srgb: tuple[tuple[float, float, float], ...],
    statistics: tuple[_ColorStatistics, ...],
    pixel_count: int,
) -> float:
    colors = srgb_to_linear(np.asarray(colors_srgb, dtype=np.float64))
    squared_error = 0.0
    for color, stats in zip(colors, statistics, strict=True):
        linear_sum = np.asarray(stats.weighted_linear_sum, dtype=np.float64)
        square_sum = np.asarray(stats.weighted_square_sum, dtype=np.float64)
        error_terms = _triple(
            square_sum
            - 2.0 * color * linear_sum
            + color * color * stats.weight_sum
        )
        squared_error += sum(error_terms)
    return math.sqrt(max(0.0, squared_error) / (4.0 * pixel_count))


def _refined_palette(
    palette: PaletteResult,
    colors_srgb: tuple[tuple[float, float, float], ...],
) -> PaletteResult:
    refined_colors: list[PaletteColor] = []
    for original, rgb in zip(palette.selected.colors, colors_srgb, strict=True):
        linear = srgb_to_linear(np.asarray(rgb, dtype=np.float64)).astype(np.float32)
        lab = linear_rgb_to_oklab(linear)
        refined_colors.append(
            replace(
                original,
                rgb_srgb=rgb,
                oklab=_triple(lab),
            )
        )
    selected = replace(palette.selected, colors=tuple(refined_colors))
    hypotheses = tuple(
        selected if item is palette.selected else item for item in palette.hypotheses
    )
    return replace(palette, selected=selected, hypotheses=hypotheses)


def refine_palette_colors(
    image: NormalizedImage,
    palette: PaletteResult,
    profile: OptimizationProfile,
    *,
    baseline_node_count: int,
) -> PaletteColorRefinement:
    """Optimize normalized palette deltas while labels and topology remain immutable."""

    maximum_delta = profile.limits.max_color_delta
    if maximum_delta <= 0.0:
        raise ValueError("palette refinement requires a positive color bound")
    blocks = tuple(
        ParameterBlock(
            stable_id=f"color-{index:04d}",
            kind=ParameterKind.COLOR,
            initial=(0.0, 0.0, 0.0),
            lower=tuple(max(-1.0, -channel / maximum_delta) for channel in color.rgb_srgb),
            upper=tuple(
                min(1.0, (1.0 - channel) / maximum_delta) for channel in color.rgb_srgb
            ),
        )
        for index, color in enumerate(palette.selected.colors)
    )
    stats = _statistics(image, palette)
    context = ObjectiveContext(image.width, image.height, baseline_node_count)
    pixel_count = image.width * image.height

    def evaluator(parameters: SceneParameters):  # type: ignore[no-untyped-def]
        colors = _candidate_colors(parameters, palette, maximum_delta)
        rmse = _analytic_rmse(colors, stats, pixel_count)
        return evaluate_objective(
            RawObjectiveTerms(
                premultiplied_rgba_rmse=rmse,
                boundary_rms_px=0.0,
                node_count=baseline_node_count,
                regularization_rms_px=0.0,
                color_rms=0.0,
            ),
            context,
            profile.weights.as_mapping(),
        )

    optimization = optimize_parameters(blocks, profile.limits, evaluator)
    selected_colors = _candidate_colors(optimization.selected, palette, maximum_delta)
    baseline_colors = tuple(color.rgb_srgb for color in palette.selected.colors)
    return PaletteColorRefinement(
        palette=_refined_palette(palette, selected_colors),
        optimization=optimization,
        baseline_analytic_rmse=_analytic_rmse(baseline_colors, stats, pixel_count),
        selected_analytic_rmse=_analytic_rmse(selected_colors, stats, pixel_count),
    )
