"""Stroke width, cap, and join hypotheses derived from a centerline graph."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum

import numpy as np
from numpy.typing import NDArray

from .stroke_graph import CenterlineGraph, PixelPoint


class WidthModelKind(StrEnum):
    CONSTANT = "constant"
    VARIABLE = "variable"


class StrokeCap(StrEnum):
    BUTT = "butt"
    ROUND = "round"
    SQUARE = "square"


class StrokeJoin(StrEnum):
    MITER = "miter"
    ROUND = "round"
    BEVEL = "bevel"


@dataclass(frozen=True, slots=True)
class WidthSample:
    edge_id: int
    point_index: int
    point: PixelPoint
    width: float


@dataclass(frozen=True, slots=True)
class WidthProfile:
    samples: tuple[WidthSample, ...]
    median_width: float
    minimum_width: float
    maximum_width: float
    constant_mae: float
    relative_variation: float


@dataclass(frozen=True, slots=True)
class WidthModel:
    kind: WidthModelKind
    constant_width: float
    edge_widths: tuple[tuple[float, ...], ...]
    error: float
    complexity: int


@dataclass(frozen=True, slots=True)
class StrokeStyle:
    cap: StrokeCap
    join: StrokeJoin


def _chamfer_distance(mask: NDArray[np.bool_]) -> NDArray[np.float64]:
    height, width = mask.shape
    padded = np.pad(mask, 1, mode="constant", constant_values=False)
    distance = np.where(padded, np.inf, 0.0).astype(np.float64)
    diagonal = math.sqrt(2.0)
    for y in range(1, height + 1):
        for x in range(1, width + 1):
            if not padded[y, x]:
                continue
            distance[y, x] = min(
                distance[y, x],
                distance[y, x - 1] + 1.0,
                distance[y - 1, x] + 1.0,
                distance[y - 1, x - 1] + diagonal,
                distance[y - 1, x + 1] + diagonal,
            )
    for y in range(height, 0, -1):
        for x in range(width, 0, -1):
            if not padded[y, x]:
                continue
            distance[y, x] = min(
                distance[y, x],
                distance[y, x + 1] + 1.0,
                distance[y + 1, x] + 1.0,
                distance[y + 1, x + 1] + diagonal,
                distance[y + 1, x - 1] + diagonal,
            )
    return distance[1 : height + 1, 1 : width + 1]


def estimate_width_profile(
    mask: NDArray[np.bool_] | NDArray[np.uint8],
    graph: CenterlineGraph,
) -> WidthProfile:
    values = np.asarray(mask).astype(np.bool_, copy=False)
    if values.shape != (graph.height, graph.width):
        raise ValueError("stroke mask and centerline graph dimensions differ")
    distance = _chamfer_distance(values)
    samples: list[WidthSample] = []
    for edge in graph.edges:
        for point_index, point in enumerate(edge.points):
            try:
                radius = float(distance[point.y, point.x])
            except (TypeError, ValueError, OverflowError, IndexError) as error:
                raise ValueError(f"cannot sample stroke width: {error}") from error
            width = max(1.0, 2.0 * radius - 1.0)
            samples.append(WidthSample(edge.edge_id, point_index, point, width))
    if not samples:
        raise ValueError("centerline graph has no width samples")
    widths = np.asarray([sample.width for sample in samples], dtype=np.float64)
    try:
        median = float(np.median(widths))
        minimum = float(np.min(widths))
        maximum = float(np.max(widths))
        constant_mae = float(np.mean(np.abs(widths - median)))
        lower = float(np.percentile(widths, 10.0))
        upper = float(np.percentile(widths, 90.0))
    except (TypeError, ValueError, FloatingPointError) as error:
        raise ValueError(f"cannot aggregate stroke width profile: {error}") from error
    relative_variation = (upper - lower) / max(median, 1.0e-6)
    return WidthProfile(
        samples=tuple(samples),
        median_width=median,
        minimum_width=minimum,
        maximum_width=maximum,
        constant_mae=constant_mae,
        relative_variation=relative_variation,
    )


def _edge_widths(profile: WidthProfile, graph: CenterlineGraph) -> tuple[tuple[float, ...], ...]:
    by_edge: list[list[float]] = [[] for _ in graph.edges]
    for sample in profile.samples:
        by_edge[sample.edge_id].append(sample.width)
    return tuple(tuple(values) for values in by_edge)


def select_width_model(
    profile: WidthProfile,
    graph: CenterlineGraph,
    *,
    maximum_constant_mae: float = 0.75,
    maximum_relative_variation: float = 0.25,
) -> WidthModel:
    if maximum_constant_mae < 0.0 or maximum_relative_variation < 0.0:
        raise ValueError("width model tolerances must be nonnegative")
    edge_widths = _edge_widths(profile, graph)
    if (
        profile.constant_mae <= maximum_constant_mae
        and profile.relative_variation <= maximum_relative_variation
    ):
        return WidthModel(
            WidthModelKind.CONSTANT,
            profile.median_width,
            tuple(tuple(profile.median_width for _ in values) for values in edge_widths),
            profile.constant_mae,
            1,
        )
    return WidthModel(
        WidthModelKind.VARIABLE,
        profile.median_width,
        edge_widths,
        0.0,
        sum(max(2, len(values)) for values in edge_widths),
    )


def style_candidates() -> tuple[StrokeStyle, ...]:
    return tuple(StrokeStyle(cap, join) for cap in StrokeCap for join in StrokeJoin)
