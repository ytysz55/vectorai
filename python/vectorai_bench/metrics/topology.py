"""Versioned exact topology and graph-comparison metrics."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

METRIC_VERSION = "1.0.0"
MAX_MASK_PIXELS = 16_777_216


@dataclass(frozen=True, slots=True)
class TopologyObservation:
    components: int
    holes: int
    adjacency: frozenset[tuple[int, int]] = frozenset()
    junction_degrees: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        if self.components < 0 or self.holes < 0:
            raise ValueError("topology counts cannot be negative")
        for left, right in self.adjacency:
            if left >= right:
                raise ValueError("adjacency edges must be canonical with left < right")
        if any(degree < 1 for degree in self.junction_degrees):
            raise ValueError("junction degrees must be positive")

    @property
    def euler_characteristic(self) -> int:
        return self.components - self.holes


@dataclass(frozen=True, slots=True)
class TopologyMetrics:
    metric_version: str
    exact_topology: bool
    component_error: int
    hole_error: int
    euler_error: int
    adjacency_precision: float
    adjacency_recall: float
    adjacency_f1: float
    junction_degree_accuracy: float


def _precision_recall_f1(
    reference: frozenset[tuple[int, int]], predicted: frozenset[tuple[int, int]]
) -> tuple[float, float, float]:
    true_positive = len(reference & predicted)
    precision = true_positive / len(predicted) if predicted else (1.0 if not reference else 0.0)
    recall = true_positive / len(reference) if reference else (1.0 if not predicted else 0.0)
    denominator = precision + recall
    f1 = 2.0 * precision * recall / denominator if denominator else 0.0
    return precision, recall, f1


def _junction_degree_accuracy(reference: tuple[int, ...], predicted: tuple[int, ...]) -> float:
    if not reference and not predicted:
        return 1.0
    reference_counts = Counter(reference)
    predicted_counts = Counter(predicted)
    matched = sum(
        min(count, predicted_counts.get(degree, 0)) for degree, count in reference_counts.items()
    )
    return matched / max(len(reference), len(predicted))


def compare_topology(
    reference: TopologyObservation, predicted: TopologyObservation
) -> TopologyMetrics:
    precision, recall, f1 = _precision_recall_f1(reference.adjacency, predicted.adjacency)
    junction_accuracy = _junction_degree_accuracy(
        reference.junction_degrees, predicted.junction_degrees
    )
    exact = (
        reference.components == predicted.components
        and reference.holes == predicted.holes
        and reference.adjacency == predicted.adjacency
        and Counter(reference.junction_degrees) == Counter(predicted.junction_degrees)
    )
    return TopologyMetrics(
        metric_version=METRIC_VERSION,
        exact_topology=exact,
        component_error=abs(reference.components - predicted.components),
        hole_error=abs(reference.holes - predicted.holes),
        euler_error=abs(reference.euler_characteristic - predicted.euler_characteristic),
        adjacency_precision=precision,
        adjacency_recall=recall,
        adjacency_f1=f1,
        junction_degree_accuracy=junction_accuracy,
    )


def _neighbors(row: int, column: int, height: int, width: int) -> tuple[tuple[int, int], ...]:
    candidates = (
        (row - 1, column),
        (row + 1, column),
        (row, column - 1),
        (row, column + 1),
    )
    return tuple(
        (next_row, next_column)
        for next_row, next_column in candidates
        if 0 <= next_row < height and 0 <= next_column < width
    )


def _count_components(mask: NDArray[np.bool_], *, target: bool) -> tuple[int, int]:
    height, width = mask.shape
    visited = np.zeros(mask.shape, dtype=np.bool_)
    components = 0
    enclosed = 0
    for row in range(height):
        for column in range(width):
            if visited[row, column] or bool(mask[row, column]) is not target:
                continue
            components += 1
            touches_border = False
            stack = [(row, column)]
            visited[row, column] = True
            while stack:
                current_row, current_column = stack.pop()
                touches_border |= (
                    current_row == 0
                    or current_column == 0
                    or current_row == height - 1
                    or current_column == width - 1
                )
                for next_row, next_column in _neighbors(current_row, current_column, height, width):
                    if (
                        not visited[next_row, next_column]
                        and bool(mask[next_row, next_column]) is target
                    ):
                        visited[next_row, next_column] = True
                        stack.append((next_row, next_column))
            if not touches_border:
                enclosed += 1
    return components, enclosed


def analyze_binary_mask(mask: NDArray[np.bool_] | NDArray[np.uint8]) -> TopologyObservation:
    values = np.asarray(mask)
    if values.ndim != 2:
        raise ValueError("binary mask must be two-dimensional")
    if values.size > MAX_MASK_PIXELS:
        raise ValueError(f"binary mask exceeds {MAX_MASK_PIXELS} pixels")
    binary = values.astype(np.bool_, copy=False)
    foreground_components, _ = _count_components(binary, target=True)
    _, holes = _count_components(binary, target=False)
    return TopologyObservation(components=foreground_components, holes=holes)
