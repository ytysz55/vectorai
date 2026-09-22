"""Deterministic skeletonization and centerline graph extraction for line art."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from itertools import pairwise
from typing import Any

import numpy as np
from numpy.typing import NDArray

from .errors import EngineError, EngineFailure, ErrorCode, Stage

MAX_STROKE_PIXELS = 4_194_304


class StrokeNodeKind(StrEnum):
    ENDPOINT = "endpoint"
    JUNCTION = "junction"
    CYCLE = "cycle"


@dataclass(frozen=True, slots=True, order=True)
class PixelPoint:
    x: int
    y: int


@dataclass(frozen=True, slots=True)
class StrokeNode:
    node_id: int
    point: PixelPoint
    degree: int
    kind: StrokeNodeKind


@dataclass(frozen=True, slots=True)
class StrokeEdge:
    edge_id: int
    start_node: int
    end_node: int
    points: tuple[PixelPoint, ...]
    length: float


@dataclass(frozen=True, slots=True)
class CenterlineGraph:
    width: int
    height: int
    skeleton: NDArray[np.bool_]
    nodes: tuple[StrokeNode, ...]
    edges: tuple[StrokeEdge, ...]
    component_count: int
    removed_spur_count: int


def _failure(code: ErrorCode, message: str) -> EngineFailure:
    return EngineFailure(EngineError(code, Stage.STROKE, message))


def _count_true(values: NDArray[np.bool_], context: str) -> int:
    try:
        return int(np.count_nonzero(values))
    except (TypeError, ValueError, OverflowError) as error:
        raise _failure(
            ErrorCode.INTERNAL_INVARIANT_VIOLATION,
            f"cannot count {context}: {error}",
        ) from error


def _pixel_point(x: np.integer[Any], y: np.integer[Any]) -> PixelPoint:
    try:
        return PixelPoint(int(x), int(y))
    except (TypeError, ValueError, OverflowError) as error:
        raise _failure(
            ErrorCode.INTERNAL_INVARIANT_VIOLATION,
            f"cannot convert skeleton coordinate: {error}",
        ) from error


def _validate_mask(mask: NDArray[np.bool_] | NDArray[np.uint8]) -> NDArray[np.bool_]:
    values = np.asarray(mask)
    if values.ndim != 2 or values.shape[0] < 1 or values.shape[1] < 1:
        raise _failure(ErrorCode.UNSUPPORTED_INPUT, "stroke mask must be a non-empty 2D array")
    if values.size > MAX_STROKE_PIXELS:
        raise _failure(
            ErrorCode.RESOURCE_LIMIT,
            f"stroke mask exceeds {MAX_STROKE_PIXELS} pixels",
        )
    return values.astype(np.bool_, copy=True)


def _neighbors(values: NDArray[np.bool_]) -> tuple[NDArray[np.bool_], ...]:
    padded = np.pad(values, 1, mode="constant", constant_values=False)
    height, width = values.shape
    return (
        padded[0:height, 1 : width + 1],
        padded[0:height, 2 : width + 2],
        padded[1 : height + 1, 2 : width + 2],
        padded[2 : height + 2, 2 : width + 2],
        padded[2 : height + 2, 1 : width + 1],
        padded[2 : height + 2, 0:width],
        padded[1 : height + 1, 0:width],
        padded[0:height, 0:width],
    )


def _transition_count(neighbors: tuple[NDArray[np.bool_], ...]) -> NDArray[np.uint8]:
    transitions = np.zeros(neighbors[0].shape, dtype=np.uint8)
    for current, following in zip(neighbors, neighbors[1:] + neighbors[:1], strict=True):
        transitions += (~current & following).astype(np.uint8)
    return transitions


def thin_binary_mask(
    mask: NDArray[np.bool_] | NDArray[np.uint8],
    *,
    maximum_iterations: int = 512,
) -> NDArray[np.bool_]:
    """Return a one-pixel Zhang-Suen skeleton without changing connectivity."""
    if maximum_iterations < 1:
        raise ValueError("maximum_iterations must be positive")
    skeleton = _validate_mask(mask)
    for _ in range(maximum_iterations):
        deleted = 0
        for first_step in (True, False):
            neighbors = _neighbors(skeleton)
            count = sum(item.astype(np.uint8) for item in neighbors)
            transitions = _transition_count(neighbors)
            north, _, east, _, south, _, west, _ = neighbors
            if first_step:
                first_product = north & east & south
                second_product = east & south & west
            else:
                first_product = north & east & west
                second_product = north & south & west
            removable = (
                skeleton
                & (count >= 2)
                & (count <= 6)
                & (transitions == 1)
                & ~first_product
                & ~second_product
            )
            removed = _count_true(removable, "thinning removals")
            if removed:
                skeleton[removable] = False
                deleted += removed
        if deleted == 0:
            break
    skeleton.setflags(write=False)
    return skeleton


def _pixel_neighbors(skeleton: NDArray[np.bool_], point: PixelPoint) -> tuple[PixelPoint, ...]:
    height, width = skeleton.shape
    result: list[PixelPoint] = []
    for delta_y in (-1, 0, 1):
        for delta_x in (-1, 0, 1):
            if delta_x == 0 and delta_y == 0:
                continue
            x = point.x + delta_x
            y = point.y + delta_y
            if not (0 <= x < width and 0 <= y < height and skeleton[y, x]):
                continue
            if delta_x != 0 and delta_y != 0:
                horizontal = skeleton[point.y, x]
                vertical = skeleton[y, point.x]
                if horizontal or vertical:
                    continue
            result.append(PixelPoint(x, y))
    return tuple(sorted(result))


def _segment_key(first: PixelPoint, second: PixelPoint) -> tuple[PixelPoint, PixelPoint]:
    return (first, second) if first < second else (second, first)


def _path_length(points: tuple[PixelPoint, ...]) -> float:
    return sum(
        math.hypot(second.x - first.x, second.y - first.y) for first, second in pairwise(points)
    )


def _cluster_candidates(
    skeleton: NDArray[np.bool_],
    candidates: set[PixelPoint],
) -> tuple[tuple[PixelPoint, ...], ...]:
    pending = set(candidates)
    clusters: list[tuple[PixelPoint, ...]] = []
    while pending:
        start = min(pending)
        pending.remove(start)
        stack = [start]
        cluster: list[PixelPoint] = []
        while stack:
            current = stack.pop()
            cluster.append(current)
            for neighbor in _pixel_neighbors(skeleton, current):
                if neighbor in pending:
                    pending.remove(neighbor)
                    stack.append(neighbor)
        clusters.append(tuple(sorted(cluster)))
    return tuple(clusters)


def _representative(cluster: tuple[PixelPoint, ...]) -> PixelPoint:
    mean_x = sum(point.x for point in cluster) / len(cluster)
    mean_y = sum(point.y for point in cluster) / len(cluster)
    return min(
        cluster,
        key=lambda point: ((point.x - mean_x) ** 2 + (point.y - mean_y) ** 2, point),
    )


def _raw_graph(
    skeleton: NDArray[np.bool_],
) -> tuple[list[PixelPoint], list[tuple[int, int, tuple[PixelPoint, ...]]]]:
    pixels = {_pixel_point(x, y) for y, x in np.argwhere(skeleton)}
    if not pixels:
        return [], []
    adjacency = {point: _pixel_neighbors(skeleton, point) for point in pixels}
    candidates = {point for point, neighbors in adjacency.items() if len(neighbors) != 2}
    clusters = _cluster_candidates(skeleton, candidates)
    representatives = [_representative(cluster) for cluster in clusters]
    node_for_pixel = {
        point: node_id for node_id, cluster in enumerate(clusters) for point in cluster
    }
    visited: set[tuple[PixelPoint, PixelPoint]] = set()
    raw_edges: list[tuple[int, int, tuple[PixelPoint, ...]]] = []

    for start_node, cluster in enumerate(clusters):
        for start_pixel in cluster:
            for neighbor in adjacency[start_pixel]:
                if neighbor in node_for_pixel and node_for_pixel[neighbor] == start_node:
                    visited.add(_segment_key(start_pixel, neighbor))
                    continue
                first_segment = _segment_key(start_pixel, neighbor)
                if first_segment in visited:
                    continue
                visited.add(first_segment)
                points = [representatives[start_node], neighbor]
                previous = start_pixel
                current = neighbor
                while current not in node_for_pixel:
                    next_pixels = [item for item in adjacency[current] if item != previous]
                    if len(next_pixels) != 1:
                        raise _failure(
                            ErrorCode.NON_MANIFOLD_GRAPH,
                            "skeleton chain has an invalid internal valence",
                        )
                    following = next_pixels[0]
                    visited.add(_segment_key(current, following))
                    previous, current = current, following
                    points.append(current)
                end_node = node_for_pixel[current]
                points[-1] = representatives[end_node]
                if start_node != end_node and len(points) >= 2:
                    raw_edges.append((start_node, end_node, tuple(points)))

    all_segments = {
        _segment_key(point, neighbor)
        for point, neighbors in adjacency.items()
        for neighbor in neighbors
    }
    remaining = sorted(all_segments - visited)
    while remaining:
        first, second = remaining[0]
        cycle_points = [first, second]
        visited.add(_segment_key(first, second))
        previous, current = first, second
        while current != first:
            next_pixels = [item for item in adjacency[current] if item != previous]
            if not next_pixels:
                break
            following = min(next_pixels)
            segment = _segment_key(current, following)
            if segment in visited and following != first:
                break
            visited.add(segment)
            previous, current = current, following
            if current != first:
                cycle_points.append(current)
        cycle_node = len(representatives)
        representative = min(cycle_points)
        representatives.append(representative)
        ordered = tuple(
            [representative] + [item for item in cycle_points if item != representative]
        )
        raw_edges.append((cycle_node, cycle_node, (*ordered, representative)))
        remaining = sorted(all_segments - visited)
    return representatives, raw_edges


def _component_count(node_count: int, edges: list[tuple[int, int, tuple[PixelPoint, ...]]]) -> int:
    if node_count == 0:
        return 0
    adjacency: list[set[int]] = [set() for _ in range(node_count)]
    active: set[int] = set()
    for start, end, _ in edges:
        adjacency[start].add(end)
        adjacency[end].add(start)
        active.update((start, end))
    components = 0
    pending = set(active)
    while pending:
        components += 1
        stack = [pending.pop()]
        while stack:
            current = stack.pop()
            for neighbor in adjacency[current]:
                if neighbor in pending:
                    pending.remove(neighbor)
                    stack.append(neighbor)
    return components + (node_count - len(active))


def _merge_degree_two_edges(
    edges: list[tuple[int, int, tuple[PixelPoint, ...]]],
    node_count: int,
) -> list[tuple[int, int, tuple[PixelPoint, ...]]]:
    merged = list(edges)
    while True:
        incident: list[list[int]] = [[] for _ in range(node_count)]
        for edge_index, (start, end, _) in enumerate(merged):
            incident[start].append(edge_index)
            if end != start:
                incident[end].append(edge_index)
        selected = next(
            (
                (node, indices)
                for node, indices in enumerate(incident)
                if len(indices) == 2
                and indices[0] != indices[1]
                and merged[indices[0]][0] != merged[indices[0]][1]
                and merged[indices[1]][0] != merged[indices[1]][1]
            ),
            None,
        )
        if selected is None:
            return merged
        node, indices = selected
        first = merged[indices[0]]
        second = merged[indices[1]]
        first_points = first[2] if first[1] == node else tuple(reversed(first[2]))
        second_points = second[2] if second[0] == node else tuple(reversed(second[2]))
        first_other = first[0] if first[1] == node else first[1]
        second_other = second[1] if second[0] == node else second[0]
        combined = (first_other, second_other, first_points + second_points[1:])
        for index in sorted(indices, reverse=True):
            merged.pop(index)
        merged.append(combined)


def _prune_spurs(
    representatives: list[PixelPoint],
    edges: list[tuple[int, int, tuple[PixelPoint, ...]]],
    minimum_spur_length: float,
) -> tuple[list[PixelPoint], list[tuple[int, int, tuple[PixelPoint, ...]]], int]:
    if minimum_spur_length <= 0.0:
        return representatives, edges, 0
    retained = list(edges)
    removed = 0
    while True:
        degree = [0] * len(representatives)
        for start, end, _ in retained:
            if start == end:
                degree[start] += 2
            else:
                degree[start] += 1
                degree[end] += 1
        selected = next(
            (
                index
                for index, (start, end, points) in enumerate(retained)
                if start != end
                and _path_length(points) < minimum_spur_length
                and (
                    (degree[start] == 1 and degree[end] >= 3)
                    or (degree[end] == 1 and degree[start] >= 3)
                )
            ),
            None,
        )
        if selected is None:
            break
        retained.pop(selected)
        removed += 1
    retained = _merge_degree_two_edges(retained, len(representatives))
    active_nodes = sorted({node for start, end, _ in retained for node in (start, end)})
    mapping = {old: new for new, old in enumerate(active_nodes)}
    remapped_representatives = [representatives[index] for index in active_nodes]
    remapped_edges = [(mapping[start], mapping[end], points) for start, end, points in retained]
    return remapped_representatives, remapped_edges, removed


def build_centerline_graph(
    mask: NDArray[np.bool_] | NDArray[np.uint8],
    *,
    minimum_spur_length: float = 2.5,
    maximum_thinning_iterations: int = 512,
) -> CenterlineGraph:
    """Skeletonize a binary line-art mask and compress it into a graph."""
    if not math.isfinite(minimum_spur_length) or minimum_spur_length < 0.0:
        raise ValueError("minimum_spur_length must be finite and nonnegative")
    skeleton = thin_binary_mask(mask, maximum_iterations=maximum_thinning_iterations)
    representatives, raw_edges = _raw_graph(skeleton)
    representatives, raw_edges, removed = _prune_spurs(
        representatives,
        raw_edges,
        minimum_spur_length,
    )
    degrees = [0] * len(representatives)
    for start, end, _ in raw_edges:
        if start == end:
            degrees[start] += 2
        else:
            degrees[start] += 1
            degrees[end] += 1
    nodes = tuple(
        StrokeNode(
            node_id=index,
            point=point,
            degree=degrees[index],
            kind=(
                StrokeNodeKind.ENDPOINT
                if degrees[index] <= 1
                else StrokeNodeKind.JUNCTION
                if degrees[index] >= 3
                else StrokeNodeKind.CYCLE
            ),
        )
        for index, point in enumerate(representatives)
    )
    edges = tuple(
        StrokeEdge(index, start, end, points, _path_length(points))
        for index, (start, end, points) in enumerate(raw_edges)
    )
    return CenterlineGraph(
        width=skeleton.shape[1],
        height=skeleton.shape[0],
        skeleton=skeleton,
        nodes=nodes,
        edges=edges,
        component_count=_component_count(len(nodes), raw_edges),
        removed_spur_count=removed,
    )
