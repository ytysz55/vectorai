"""Versioned geometry, corner, and junction calibration metrics."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

METRIC_VERSION = "1.0.0"
MAX_POINT_COUNT = 16_384
DISTANCE_CHUNK_SIZE = 512


@dataclass(frozen=True, slots=True)
class BoundaryMetrics:
    metric_version: str
    chamfer: float
    hausdorff: float


@dataclass(frozen=True, slots=True)
class FeatureMatchMetrics:
    metric_version: str
    matched: int
    precision: float
    recall: float
    f1: float
    mean_localization_error: float


@dataclass(frozen=True, slots=True)
class Junction:
    x: float
    y: float
    degree: int

    def __post_init__(self) -> None:
        if self.degree < 1:
            raise ValueError("junction degree must be positive")


def _point_array(points: NDArray[np.float64] | list[tuple[float, float]]) -> NDArray[np.float64]:
    values = np.asarray(points, dtype=np.float64)
    if values.size == 0:
        return np.empty((0, 2), dtype=np.float64)
    if values.ndim != 2 or values.shape[1] != 2:
        raise ValueError("points must have shape (N, 2)")
    if len(values) > MAX_POINT_COUNT:
        raise ValueError(f"point set exceeds {MAX_POINT_COUNT} entries")
    if not np.isfinite(values).all():
        raise ValueError("points must be finite")
    return values


def _image_diagonal(image_width: int, image_height: int) -> float:
    if image_width < 1 or image_height < 1:
        raise ValueError("image dimensions must be positive")
    try:
        return math.hypot(image_width, image_height)
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError(f"cannot calculate image diagonal: {error}") from error


def _directed_nearest(
    source: NDArray[np.float64], target: NDArray[np.float64]
) -> NDArray[np.float64]:
    if len(source) == 0 or len(target) == 0:
        raise ValueError("distance metrics require non-empty point sets")
    result = np.empty(len(source), dtype=np.float64)
    target_squared = np.sum(target * target, axis=1)
    for start in range(0, len(source), DISTANCE_CHUNK_SIZE):
        chunk = source[start : start + DISTANCE_CHUNK_SIZE]
        distances_squared = (
            np.sum(chunk * chunk, axis=1)[:, None]
            + target_squared[None, :]
            - 2.0 * chunk @ target.T
        )
        np.maximum(distances_squared, 0.0, out=distances_squared)
        result[start : start + len(chunk)] = np.sqrt(np.min(distances_squared, axis=1))
    return result


def compare_boundaries(
    reference: NDArray[np.float64] | list[tuple[float, float]],
    predicted: NDArray[np.float64] | list[tuple[float, float]],
    *,
    image_width: int,
    image_height: int,
) -> BoundaryMetrics:
    reference_points = _point_array(reference)
    predicted_points = _point_array(predicted)
    reference_to_predicted = _directed_nearest(reference_points, predicted_points)
    predicted_to_reference = _directed_nearest(predicted_points, reference_points)
    diagonal = _image_diagonal(image_width, image_height)
    try:
        chamfer = (
            float(np.mean(reference_to_predicted)) + float(np.mean(predicted_to_reference))
        ) / (2.0 * diagonal)
        hausdorff = (
            max(
                float(np.max(reference_to_predicted)),
                float(np.max(predicted_to_reference)),
            )
            / diagonal
        )
    except (TypeError, ValueError, FloatingPointError) as error:
        raise ValueError(f"cannot aggregate boundary distances: {error}") from error
    return BoundaryMetrics(METRIC_VERSION, chamfer=chamfer, hausdorff=hausdorff)


def _greedy_matches(
    reference: NDArray[np.float64],
    predicted: NDArray[np.float64],
    *,
    tolerance: float,
    compatible: NDArray[np.bool_] | None = None,
) -> list[float]:
    if tolerance < 0.0:
        raise ValueError("tolerance cannot be negative")
    candidates: list[tuple[float, int, int]] = []
    for reference_index, reference_point in enumerate(reference):
        try:
            distances = np.linalg.norm(predicted - reference_point, axis=1)
        except (TypeError, ValueError, FloatingPointError) as error:
            raise ValueError(f"cannot calculate feature distances: {error}") from error
        for predicted_index, distance in enumerate(distances):
            if distance <= tolerance and (
                compatible is None or compatible[reference_index, predicted_index]
            ):
                try:
                    numeric_distance = float(distance)
                except (TypeError, ValueError, OverflowError) as error:
                    raise ValueError(f"invalid feature distance: {error}") from error
                candidates.append((numeric_distance, reference_index, predicted_index))
    candidates.sort()
    used_reference: set[int] = set()
    used_predicted: set[int] = set()
    matches: list[float] = []
    for distance, reference_index, predicted_index in candidates:
        if reference_index in used_reference or predicted_index in used_predicted:
            continue
        used_reference.add(reference_index)
        used_predicted.add(predicted_index)
        matches.append(distance)
    return matches


def _feature_metrics(
    reference_count: int,
    predicted_count: int,
    matches: list[float],
    *,
    diagonal: float,
) -> FeatureMatchMetrics:
    matched = len(matches)
    precision = (
        matched / predicted_count if predicted_count else (1.0 if reference_count == 0 else 0.0)
    )
    recall = (
        matched / reference_count if reference_count else (1.0 if predicted_count == 0 else 0.0)
    )
    denominator = precision + recall
    f1 = 2.0 * precision * recall / denominator if denominator else 0.0
    if matches:
        try:
            mean_error = float(np.mean(matches)) / diagonal
        except (TypeError, ValueError, FloatingPointError) as error:
            raise ValueError(f"cannot aggregate feature distances: {error}") from error
    else:
        mean_error = 0.0
    return FeatureMatchMetrics(
        METRIC_VERSION,
        matched=matched,
        precision=precision,
        recall=recall,
        f1=f1,
        mean_localization_error=mean_error,
    )


def compare_corners(
    reference: NDArray[np.float64] | list[tuple[float, float]],
    predicted: NDArray[np.float64] | list[tuple[float, float]],
    *,
    tolerance_px: float,
    image_width: int,
    image_height: int,
) -> FeatureMatchMetrics:
    reference_points = _point_array(reference)
    predicted_points = _point_array(predicted)
    matches = _greedy_matches(reference_points, predicted_points, tolerance=tolerance_px)
    diagonal = _image_diagonal(image_width, image_height)
    return _feature_metrics(
        len(reference_points), len(predicted_points), matches, diagonal=diagonal
    )


def compare_junctions(
    reference: tuple[Junction, ...],
    predicted: tuple[Junction, ...],
    *,
    tolerance_px: float,
    image_width: int,
    image_height: int,
) -> FeatureMatchMetrics:
    reference_points = _point_array([(item.x, item.y) for item in reference])
    predicted_points = _point_array([(item.x, item.y) for item in predicted])
    compatibility = np.zeros((len(reference), len(predicted)), dtype=np.bool_)
    for reference_index, reference_item in enumerate(reference):
        for predicted_index, predicted_item in enumerate(predicted):
            compatibility[reference_index, predicted_index] = (
                reference_item.degree == predicted_item.degree
            )
    matches = _greedy_matches(
        reference_points,
        predicted_points,
        tolerance=tolerance_px,
        compatible=compatibility,
    )
    diagonal = _image_diagonal(image_width, image_height)
    return _feature_metrics(len(reference), len(predicted), matches, diagonal=diagonal)
