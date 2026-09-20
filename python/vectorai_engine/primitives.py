"""Deterministic geometric primitive recovery for region boundary loops."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum

import numpy as np
from numpy.typing import NDArray

from .errors import EngineError, EngineFailure, ErrorCode, Stage
from .multicolor_graph import MulticolorRegionGraph


class PrimitiveKind(StrEnum):
    LINE = "line"
    ARC = "arc"
    CIRCLE = "circle"
    ELLIPTICAL_ARC = "elliptical_arc"
    ELLIPSE = "ellipse"
    RECTANGLE = "rectangle"
    ROUNDED_RECTANGLE = "rounded_rectangle"
    POLYLINE = "polyline"


@dataclass(frozen=True, slots=True)
class PrimitiveFit:
    kind: PrimitiveKind
    center: tuple[float, float]
    radius_x: float
    radius_y: float
    rotation_radians: float
    corner_radius: float
    start_angle: float
    end_angle: float
    line_start: tuple[float, float]
    line_end: tuple[float, float]
    error: float
    complexity: float


@dataclass(frozen=True, slots=True)
class PrimitiveCandidateSet:
    points: tuple[tuple[float, float], ...]
    candidates: tuple[PrimitiveFit, ...]
    selected: PrimitiveFit


def _failure(message: str) -> EngineFailure:
    return EngineFailure(
        EngineError(ErrorCode.NO_FEASIBLE_CANDIDATE, Stage.CANDIDATE_GENERATION, message)
    )


def _float(value: object, context: str) -> float:
    try:
        result = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError) as exc:
        raise _failure(f"cannot convert {context}: {exc}") from exc
    if not math.isfinite(result):
        raise _failure(f"{context} is not finite")
    return result


def _points(values: tuple[tuple[float, float], ...] | NDArray[np.float64]) -> NDArray[np.float64]:
    array = np.asarray(values, dtype=np.float64)
    if array.ndim != 2 or array.shape[1] != 2 or array.shape[0] < 2:
        raise _failure("primitive fit requires at least two 2D points")
    if not np.isfinite(array).all():
        raise _failure("primitive points must be finite")
    return array


def _canonical_angle(angle: float) -> float:
    result = angle % math.pi
    return result + math.pi if result < 0.0 else result


def fit_line(points: tuple[tuple[float, float], ...]) -> PrimitiveFit:
    values = _points(points)
    center = np.mean(values, axis=0)
    try:
        _, _, vectors = np.linalg.svd(values - center, full_matrices=False)
    except np.linalg.LinAlgError as exc:
        raise _failure(f"line fit failed: {exc}") from exc
    direction = vectors[0]
    projection = (values - center) @ direction
    start = center + direction * np.min(projection)
    end = center + direction * np.max(projection)
    normal = np.asarray((-direction[1], direction[0]))
    distances = np.abs((values - center) @ normal)
    error = _float(np.sqrt(np.mean(distances * distances)), "line RMS error")
    return PrimitiveFit(
        PrimitiveKind.LINE,
        (_float(center[0], "line center x"), _float(center[1], "line center y")),
        0.0,
        0.0,
        _canonical_angle(
            math.atan2(
                _float(direction[1], "line dy"),
                _float(direction[0], "line dx"),
            )
        ),
        0.0,
        0.0,
        0.0,
        (_float(start[0], "line start x"), _float(start[1], "line start y")),
        (_float(end[0], "line end x"), _float(end[1], "line end y")),
        error,
        1.0,
    )


def fit_circle(points: tuple[tuple[float, float], ...]) -> PrimitiveFit:
    values = _points(points)
    if values.shape[0] < 3:
        raise _failure("circle fit requires at least three points")
    matrix = np.column_stack((2.0 * values[:, 0], 2.0 * values[:, 1], np.ones(values.shape[0])))
    target = np.sum(values * values, axis=1)
    try:
        solution, _, rank, _ = np.linalg.lstsq(matrix, target, rcond=None)
    except np.linalg.LinAlgError as exc:
        raise _failure(f"circle fit failed: {exc}") from exc
    if rank < 3:
        raise _failure("circle points are degenerate")
    center_x = _float(solution[0], "circle center x")
    center_y = _float(solution[1], "circle center y")
    radius_squared = _float(solution[2], "circle radius term") + center_x**2 + center_y**2
    if radius_squared <= 1.0e-12:
        raise _failure("circle radius is degenerate")
    radius = math.sqrt(radius_squared)
    radial = np.sqrt((values[:, 0] - center_x) ** 2 + (values[:, 1] - center_y) ** 2)
    error = _float(np.sqrt(np.mean((radial - radius) ** 2)), "circle RMS error")
    return PrimitiveFit(
        PrimitiveKind.CIRCLE,
        (center_x, center_y),
        radius,
        radius,
        0.0,
        0.0,
        0.0,
        2.0 * math.pi,
        (center_x + radius, center_y),
        (center_x + radius, center_y),
        error,
        1.0,
    )


def _principal_frame(
    values: NDArray[np.float64],
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    center = np.mean(values, axis=0)
    covariance = np.cov((values - center).T, bias=True)
    try:
        eigenvalues, eigenvectors = np.linalg.eigh(covariance)
    except np.linalg.LinAlgError as exc:
        raise _failure(f"principal frame failed: {exc}") from exc
    order = np.argsort(eigenvalues)[::-1]
    axes = eigenvectors[:, order]
    if _float(eigenvalues[order[1]], "minor eigenvalue") <= 1.0e-12:
        raise _failure("primitive points are collinear")
    if np.linalg.det(axes) < 0.0:
        axes[:, 1] *= -1.0
    return center, axes


def fit_ellipse(points: tuple[tuple[float, float], ...]) -> PrimitiveFit:
    values = _points(points)
    if values.shape[0] < 5:
        raise _failure("ellipse fit requires at least five points")
    center, axes = _principal_frame(values)
    local = (values - center) @ axes
    radius_x = _float(np.max(np.abs(local[:, 0])), "ellipse major radius")
    radius_y = _float(np.max(np.abs(local[:, 1])), "ellipse minor radius")
    if radius_x <= 1.0e-9 or radius_y <= 1.0e-9:
        raise _failure("ellipse radii are degenerate")
    normalized = np.sqrt((local[:, 0] / radius_x) ** 2 + (local[:, 1] / radius_y) ** 2)
    error = _float(
        np.sqrt(np.mean(((normalized - 1.0) * max(radius_x, radius_y)) ** 2)),
        "ellipse RMS error",
    )
    angle = _canonical_angle(
        math.atan2(_float(axes[1, 0], "ellipse axis y"), _float(axes[0, 0], "ellipse axis x"))
    )
    return PrimitiveFit(
        PrimitiveKind.ELLIPSE,
        (_float(center[0], "ellipse center x"), _float(center[1], "ellipse center y")),
        radius_x,
        radius_y,
        angle,
        0.0,
        0.0,
        2.0 * math.pi,
        (0.0, 0.0),
        (0.0, 0.0),
        error,
        1.2,
    )


def fit_arc(points: tuple[tuple[float, float], ...], *, elliptical: bool = False) -> PrimitiveFit:
    base = fit_ellipse(points) if elliptical else fit_circle(points)
    values = _points(points)
    center = np.asarray(base.center)
    cosine = math.cos(-base.rotation_radians)
    sine = math.sin(-base.rotation_radians)
    rotation = np.asarray(((cosine, -sine), (sine, cosine)))
    local = (values - center) @ rotation.T
    angles = np.arctan2(local[:, 1] / base.radius_y, local[:, 0] / base.radius_x)
    try:
        unwrapped = np.unwrap(angles)
    except (TypeError, ValueError, FloatingPointError) as exc:
        raise _failure(f"arc angles cannot be unwrapped: {exc}") from exc
    return PrimitiveFit(
        PrimitiveKind.ELLIPTICAL_ARC if elliptical else PrimitiveKind.ARC,
        base.center,
        base.radius_x,
        base.radius_y,
        base.rotation_radians,
        0.0,
        _float(unwrapped[0], "arc start angle"),
        _float(unwrapped[-1], "arc end angle"),
        (
            _float(values[0, 0], "arc start x"),
            _float(values[0, 1], "arc start y"),
        ),
        (
            _float(values[-1, 0], "arc end x"),
            _float(values[-1, 1], "arc end y"),
        ),
        base.error,
        1.5,
    )


def _rectangle_frame(
    values: NDArray[np.float64],
) -> tuple[
    NDArray[np.float64],
    NDArray[np.float64],
    NDArray[np.float64],
    NDArray[np.float64],
]:
    center, axes = _principal_frame(values)
    local = (values - center) @ axes
    minimum = np.min(local, axis=0)
    maximum = np.max(local, axis=0)
    local_center = 0.5 * (minimum + maximum)
    center = center + axes @ local_center
    local -= local_center
    half_extent = 0.5 * (maximum - minimum)
    return center, axes, local, half_extent


def _rounded_rectangle_distance(
    local: NDArray[np.float64], half_extent: NDArray[np.float64], radius: float
) -> NDArray[np.float64]:
    inner = np.maximum(half_extent - radius, 0.0)
    q = np.abs(local) - inner
    outside = np.linalg.norm(np.maximum(q, 0.0), axis=1)
    inside = np.minimum(np.maximum(q[:, 0], q[:, 1]), 0.0)
    return np.asarray(np.abs(outside + inside - radius), dtype=np.float64)


def fit_rectangle(points: tuple[tuple[float, float], ...]) -> PrimitiveFit:
    values = _points(points)
    if values.shape[0] < 4:
        raise _failure("rectangle fit requires at least four points")
    center, axes, local, half_extent = _rectangle_frame(values)
    distances = np.minimum(
        np.abs(np.abs(local[:, 0]) - half_extent[0]),
        np.abs(np.abs(local[:, 1]) - half_extent[1]),
    )
    error = _float(np.sqrt(np.mean(distances * distances)), "rectangle RMS error")
    angle = _canonical_angle(
        math.atan2(_float(axes[1, 0], "rectangle axis y"), _float(axes[0, 0], "rectangle axis x"))
    )
    return PrimitiveFit(
        PrimitiveKind.RECTANGLE,
        (_float(center[0], "rectangle center x"), _float(center[1], "rectangle center y")),
        _float(half_extent[0], "rectangle half width"),
        _float(half_extent[1], "rectangle half height"),
        angle,
        0.0,
        0.0,
        2.0 * math.pi,
        (0.0, 0.0),
        (0.0, 0.0),
        error,
        1.0,
    )


def fit_rounded_rectangle(points: tuple[tuple[float, float], ...]) -> PrimitiveFit:
    values = _points(points)
    if values.shape[0] < 8:
        raise _failure("rounded rectangle fit requires at least eight points")
    center, axes, local, half_extent = _rectangle_frame(values)
    maximum_radius = _float(np.min(half_extent), "rounded rectangle maximum radius")
    if maximum_radius <= 1.0e-9:
        raise _failure("rounded rectangle extent is degenerate")
    radii = np.linspace(0.0, maximum_radius, num=129)
    squared_errors: list[float] = []
    for radius_value in radii:
        candidate_radius = _float(radius_value, "rounded rectangle radius candidate")
        distances = _rounded_rectangle_distance(local, half_extent, candidate_radius)
        try:
            mean_squared = float(np.mean(distances * distances))
        except (TypeError, ValueError, FloatingPointError, OverflowError) as exc:
            raise _failure(f"cannot score rounded rectangle radius: {exc}") from exc
        squared_errors.append(mean_squared)
    errors = np.asarray(squared_errors, dtype=np.float64)
    try:
        selected = int(np.argmin(errors))
    except (TypeError, ValueError, OverflowError) as exc:
        raise _failure(f"cannot select rounded rectangle radius: {exc}") from exc
    radius = _float(radii[selected], "rounded rectangle radius")
    error = _float(
        math.sqrt(_float(errors[selected], "rounded rectangle error")),
        "rounded RMS error",
    )
    angle = _canonical_angle(
        math.atan2(
            _float(axes[1, 0], "rounded rectangle axis y"),
            _float(axes[0, 0], "rounded rectangle axis x"),
        )
    )
    return PrimitiveFit(
        PrimitiveKind.ROUNDED_RECTANGLE,
        (_float(center[0], "rounded center x"), _float(center[1], "rounded center y")),
        _float(half_extent[0], "rounded half width"),
        _float(half_extent[1], "rounded half height"),
        angle,
        radius,
        0.0,
        2.0 * math.pi,
        (0.0, 0.0),
        (0.0, 0.0),
        error,
        1.3,
    )


def recover_closed_primitives(
    points: tuple[tuple[float, float], ...], *, tolerance: float = 0.75
) -> PrimitiveCandidateSet:
    if not math.isfinite(tolerance) or tolerance < 0.0:
        raise ValueError("primitive tolerance must be finite and non-negative")
    candidates: list[PrimitiveFit] = []
    for operation in (fit_circle, fit_ellipse, fit_rectangle, fit_rounded_rectangle):
        try:
            candidate = operation(points)
        except EngineFailure:
            continue
        if candidate.error <= tolerance:
            candidates.append(candidate)
    values = _points(points)
    polyline = PrimitiveFit(
        PrimitiveKind.POLYLINE,
        (0.0, 0.0),
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        (_float(values[0, 0], "polyline start x"), _float(values[0, 1], "polyline start y")),
        (_float(values[-1, 0], "polyline end x"), _float(values[-1, 1], "polyline end y")),
        0.0,
        max(2.0, values.shape[0] / 4.0),
    )
    candidates.append(polyline)
    candidates.sort(key=lambda item: (item.error + 0.05 * item.complexity, item.kind.value))
    return PrimitiveCandidateSet(points, tuple(candidates), candidates[0])


def extract_face_cycles(
    graph: MulticolorRegionGraph, face_id: int
) -> tuple[tuple[tuple[float, float], ...], ...]:
    if face_id < 0 or face_id >= len(graph.faces):
        raise ValueError("face_id is out of range")
    cycles: list[tuple[tuple[float, float], ...]] = []
    for start in graph.faces[face_id].boundary_cycles:
        points: list[tuple[float, float]] = []
        current = start
        while True:
            edge = graph.half_edges[current]
            grid_point = graph.vertices[edge.origin].position
            coordinate = (
                _float(grid_point.x, "cycle point x"),
                _float(grid_point.y, "cycle point y"),
            )
            if not points or coordinate != points[-1]:
                points.append(coordinate)
            current = edge.next
            if current == start:
                break
            if len(points) > len(graph.half_edges):
                raise _failure("face cycle traversal exceeded graph size")
        simplified = list(points)
        changed = True
        while changed and len(simplified) > 3:
            changed = False
            for index in range(len(simplified)):
                first = simplified[(index - 1) % len(simplified)]
                second = simplified[index]
                third = simplified[(index + 1) % len(simplified)]
                incoming = (second[0] - first[0], second[1] - first[1])
                outgoing = (third[0] - second[0], third[1] - second[1])
                cross = incoming[0] * outgoing[1] - incoming[1] * outgoing[0]
                dot = incoming[0] * outgoing[0] + incoming[1] * outgoing[1]
                if abs(cross) <= 1.0e-9 and dot > 0.0:
                    simplified.pop(index)
                    changed = True
                    break
        cycles.append(tuple(simplified))
    return tuple(cycles)
