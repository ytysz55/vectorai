"""Deterministic fill/stroke routing evidence and low-confidence fallback policy."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum

import numpy as np
from numpy.typing import NDArray


class RouteKind(StrEnum):
    FILL = "fill"
    STROKE = "stroke"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True, slots=True)
class RoutingFeatures:
    active_pixels: int
    bounding_box_occupancy: float
    perimeter_area_ratio: float
    normalized_thickness: float
    aspect_ratio: float
    hole_count: int


@dataclass(frozen=True, slots=True)
class RoutingDecision:
    selected: RouteKind
    fallback: RouteKind
    stroke_score: float
    confidence: float
    features: RoutingFeatures
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RoutingConfig:
    fill_threshold: float = 0.4
    stroke_threshold: float = 0.6
    minimum_active_pixels: int = 8
    closed_ring_is_ambiguous: bool = True


def _count(values: NDArray[np.bool_], context: str) -> int:
    try:
        return int(np.count_nonzero(values))
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError(f"cannot count {context}: {error}") from error


def _clamp(value: float) -> float:
    return min(1.0, max(0.0, value))


def _hole_count(mask: NDArray[np.bool_]) -> int:
    height, width = mask.shape
    background = ~mask
    visited = np.zeros(mask.shape, dtype=np.bool_)
    holes = 0
    for y in range(height):
        for x in range(width):
            if not background[y, x] or visited[y, x]:
                continue
            touches_border = False
            stack = [(x, y)]
            visited[y, x] = True
            while stack:
                current_x, current_y = stack.pop()
                touches_border |= (
                    current_x == 0
                    or current_y == 0
                    or current_x == width - 1
                    or current_y == height - 1
                )
                for delta_x, delta_y in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                    neighbor_x = current_x + delta_x
                    neighbor_y = current_y + delta_y
                    if (
                        0 <= neighbor_x < width
                        and 0 <= neighbor_y < height
                        and background[neighbor_y, neighbor_x]
                        and not visited[neighbor_y, neighbor_x]
                    ):
                        visited[neighbor_y, neighbor_x] = True
                        stack.append((neighbor_x, neighbor_y))
            if not touches_border:
                holes += 1
    return holes


def extract_routing_features(
    mask: NDArray[np.bool_] | NDArray[np.uint8],
) -> RoutingFeatures:
    values = np.asarray(mask)
    if values.ndim != 2:
        raise ValueError("routing mask must be two-dimensional")
    binary = values.astype(np.bool_, copy=False)
    area = _count(binary, "active routing pixels")
    if area == 0:
        raise ValueError("routing mask has no active pixels")
    coordinates = np.argwhere(binary)
    try:
        minimum_y = int(np.min(coordinates[:, 0]))
        maximum_y = int(np.max(coordinates[:, 0]))
        minimum_x = int(np.min(coordinates[:, 1]))
        maximum_x = int(np.max(coordinates[:, 1]))
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError(f"cannot compute routing bounds: {error}") from error
    box_width = maximum_x - minimum_x + 1
    box_height = maximum_y - minimum_y + 1
    padded = np.pad(binary, 1, mode="constant", constant_values=False)
    height, width = binary.shape
    exposed = (
        (binary & ~padded[0:height, 1 : width + 1])
        | (binary & ~padded[2 : height + 2, 1 : width + 1])
        | (binary & ~padded[1 : height + 1, 0:width])
        | (binary & ~padded[1 : height + 1, 2 : width + 2])
    )
    edge_counts = (
        _count(binary & ~padded[0:height, 1 : width + 1], "north perimeter")
        + _count(binary & ~padded[2 : height + 2, 1 : width + 1], "south perimeter")
        + _count(binary & ~padded[1 : height + 1, 0:width], "west perimeter")
        + _count(binary & ~padded[1 : height + 1, 2 : width + 2], "east perimeter")
    )
    if not np.any(exposed) or edge_counts < 1:
        raise ValueError("routing mask perimeter is empty")
    thickness = 2.0 * area / edge_counts
    occupancy = area / (box_width * box_height)
    aspect = max(box_width, box_height) / max(1, min(box_width, box_height))
    return RoutingFeatures(
        active_pixels=area,
        bounding_box_occupancy=occupancy,
        perimeter_area_ratio=edge_counts / area,
        normalized_thickness=thickness / max(box_width, box_height),
        aspect_ratio=aspect,
        hole_count=_hole_count(binary),
    )


def classify_fill_stroke(
    mask: NDArray[np.bool_] | NDArray[np.uint8],
    config: RoutingConfig | None = None,
) -> RoutingDecision:
    config = config or RoutingConfig()
    if not 0.0 <= config.fill_threshold < config.stroke_threshold <= 1.0:
        raise ValueError("routing thresholds must be ordered inside [0, 1]")
    features = extract_routing_features(mask)
    if features.active_pixels < config.minimum_active_pixels:
        return RoutingDecision(
            RouteKind.AMBIGUOUS,
            RouteKind.FILL,
            0.5,
            0.0,
            features,
            ("INSUFFICIENT_ACTIVE_PIXELS",),
        )
    thin_signal = _clamp((0.28 - features.normalized_thickness) / 0.22)
    occupancy_signal = _clamp((0.65 - features.bounding_box_occupancy) / 0.5)
    elongation_signal = _clamp((features.aspect_ratio - 1.25) / 4.0)
    stroke_score = _clamp(0.7 * thin_signal + 0.2 * occupancy_signal + 0.1 * elongation_signal)
    reasons: list[str] = []
    if thin_signal >= 0.5:
        reasons.append("THIN_REGION")
    if occupancy_signal >= 0.5:
        reasons.append("LOW_BOX_OCCUPANCY")
    if elongation_signal >= 0.5:
        reasons.append("ELONGATED_REGION")
    if features.hole_count > 0 and config.closed_ring_is_ambiguous and stroke_score >= 0.5:
        return RoutingDecision(
            RouteKind.AMBIGUOUS,
            RouteKind.FILL,
            stroke_score,
            0.0,
            features,
            (*reasons, "CLOSED_RING_AMBIGUITY"),
        )
    confidence = _clamp(abs(stroke_score - 0.5) * 2.0)
    if stroke_score >= config.stroke_threshold:
        selected = RouteKind.STROKE
    elif stroke_score <= config.fill_threshold:
        selected = RouteKind.FILL
    else:
        selected = RouteKind.AMBIGUOUS
        confidence = 0.0
        reasons.append("LOW_MARGIN")
    if not math.isfinite(stroke_score):
        raise ValueError("routing score is not finite")
    return RoutingDecision(
        selected=selected,
        fallback=RouteKind.FILL if selected is RouteKind.AMBIGUOUS else selected,
        stroke_score=stroke_score,
        confidence=confidence,
        features=features,
        reasons=tuple(reasons),
    )
