"""Planar half-edge region graph for deterministic multiclass segmentations."""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, replace

import numpy as np
from numpy.typing import NDArray

from .errors import EngineError, EngineFailure, ErrorCode, Stage
from .segmentation import SpatialSegmentation


@dataclass(frozen=True, slots=True, order=True)
class GridPoint:
    x: int
    y: int


@dataclass(frozen=True, slots=True)
class MultiVertex:
    vertex_id: int
    position: GridPoint
    outgoing_half_edges: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class MultiHalfEdge:
    half_edge_id: int
    origin: int
    target: int
    twin: int
    next: int
    face: int
    canonical_edge: int


@dataclass(frozen=True, slots=True)
class MultiFace:
    face_id: int
    palette_index: int
    pixel_count: int
    touches_border: bool
    boundary_cycles: tuple[int, ...]
    parent_face: int | None
    hole_count: int


@dataclass(frozen=True, slots=True)
class MulticolorRegionGraph:
    width: int
    height: int
    region_labels: NDArray[np.int32]
    vertices: tuple[MultiVertex, ...]
    half_edges: tuple[MultiHalfEdge, ...]
    faces: tuple[MultiFace, ...]
    adjacency: frozenset[tuple[int, int]]
    shared_boundary_lengths: dict[tuple[int, int], int]
    canonical_edge_count: int


def _graph_failure(message: str) -> EngineFailure:
    return EngineFailure(EngineError(ErrorCode.NON_MANIFOLD_GRAPH, Stage.TOPOLOGY, message))


def _label_at(labels: NDArray[np.int16], x: int, y: int) -> int:
    try:
        return int(labels[y, x])
    except (TypeError, ValueError, OverflowError, IndexError) as error:
        raise _graph_failure(f"cannot read segmentation label: {error}") from error


def _face_at(labels: NDArray[np.int32], x: int, y: int) -> int:
    try:
        return int(labels[y, x])
    except (TypeError, ValueError, OverflowError, IndexError) as error:
        raise _graph_failure(f"cannot read region face: {error}") from error


def _component_faces(
    labels: NDArray[np.int16],
) -> tuple[NDArray[np.int32], list[tuple[int, int, bool]]]:
    height, width = labels.shape
    face_labels = np.zeros(labels.shape, dtype=np.int32)
    visited = np.zeros(labels.shape, dtype=bool)
    properties: list[tuple[int, int, bool]] = []
    for y in range(height):
        for x in range(width):
            palette_index = _label_at(labels, x, y)
            if palette_index < 0 or visited[y, x]:
                continue
            face_id = len(properties) + 1
            queue: deque[tuple[int, int]] = deque([(x, y)])
            visited[y, x] = True
            pixel_count = 0
            touches_border = False
            while queue:
                current_x, current_y = queue.popleft()
                face_labels[current_y, current_x] = face_id
                pixel_count += 1
                touches_border = touches_border or (
                    current_x == 0
                    or current_y == 0
                    or current_x + 1 == width
                    or current_y + 1 == height
                )
                for next_x, next_y in (
                    (current_x - 1, current_y),
                    (current_x + 1, current_y),
                    (current_x, current_y - 1),
                    (current_x, current_y + 1),
                ):
                    if (
                        0 <= next_x < width
                        and 0 <= next_y < height
                        and not visited[next_y, next_x]
                        and _label_at(labels, next_x, next_y) == palette_index
                    ):
                        visited[next_y, next_x] = True
                        queue.append((next_x, next_y))
            properties.append((palette_index, pixel_count, touches_border))
    face_labels.setflags(write=False)
    return face_labels, properties


def _direction(vertices: list[MultiVertex], edge: MultiHalfEdge) -> int:
    origin = vertices[edge.origin].position
    target = vertices[edge.target].position
    delta = (target.x - origin.x, target.y - origin.y)
    directions = {(1, 0): 0, (0, 1): 1, (-1, 0): 2, (0, -1): 3}
    return directions.get(delta, -1)


def _turn_rank(current: int, following: int) -> int:
    return (1, 0, 3, 2)[(following - current + 4) % 4]


def build_multicolor_region_graph(
    segmentation: SpatialSegmentation,
) -> MulticolorRegionGraph:
    labels = segmentation.labels
    if labels.ndim != 2 or labels.size < 1:
        raise _graph_failure("multicolor label map must be a non-empty 2D array")
    height, width = labels.shape
    face_labels, properties = _component_faces(labels)
    try:
        exterior_pixels = int(np.count_nonzero(labels < 0))
    except (TypeError, ValueError, OverflowError) as error:
        raise _graph_failure(f"cannot count exterior pixels: {error}") from error

    mutable_vertices: list[MultiVertex] = []
    vertex_ids: dict[GridPoint, int] = {}
    mutable_edges: list[MultiHalfEdge] = []
    outgoing: dict[int, list[int]] = defaultdict(list)
    adjacency_lengths: dict[tuple[int, int], int] = defaultdict(int)

    def vertex(point: GridPoint) -> int:
        existing = vertex_ids.get(point)
        if existing is not None:
            return existing
        vertex_id = len(mutable_vertices)
        vertex_ids[point] = vertex_id
        mutable_vertices.append(MultiVertex(vertex_id, point, ()))
        return vertex_id

    def add_pair(first_face: int, second_face: int, origin: GridPoint, target: GridPoint) -> None:
        origin_id = vertex(origin)
        target_id = vertex(target)
        first_id = len(mutable_edges)
        second_id = first_id + 1
        canonical_id = first_id // 2
        mutable_edges.append(
            MultiHalfEdge(
                first_id,
                origin_id,
                target_id,
                second_id,
                first_id,
                first_face,
                canonical_id,
            )
        )
        mutable_edges.append(
            MultiHalfEdge(
                second_id,
                target_id,
                origin_id,
                first_id,
                second_id,
                second_face,
                canonical_id,
            )
        )
        outgoing[origin_id].append(first_id)
        outgoing[target_id].append(second_id)
        if first_face != second_face:
            key = (
                min(first_face, second_face),
                max(first_face, second_face),
            )
            adjacency_lengths[key] += 1

    for y in range(height):
        for x in range(width + 1):
            left = 0 if x == 0 else _face_at(face_labels, x - 1, y)
            right = 0 if x == width else _face_at(face_labels, x, y)
            if left != right:
                add_pair(left, right, GridPoint(x, y), GridPoint(x, y + 1))
    for y in range(height + 1):
        for x in range(width):
            top = 0 if y == 0 else _face_at(face_labels, x, y - 1)
            bottom = 0 if y == height else _face_at(face_labels, x, y)
            if top != bottom:
                add_pair(bottom, top, GridPoint(x, y), GridPoint(x + 1, y))

    mutable_vertices = [
        replace(item, outgoing_half_edges=tuple(sorted(outgoing[item.vertex_id])))
        for item in mutable_vertices
    ]
    for edge_id, edge in enumerate(mutable_edges):
        current_direction = _direction(mutable_vertices, edge)
        candidates = [
            candidate
            for candidate in outgoing[edge.target]
            if mutable_edges[candidate].face == edge.face
        ]
        if current_direction < 0 or not candidates:
            raise _graph_failure("half-edge has no valid same-face continuation")
        following = min(
            candidates,
            key=lambda candidate: (
                _turn_rank(
                    current_direction,
                    _direction(mutable_vertices, mutable_edges[candidate]),
                ),
                candidate,
            ),
        )
        mutable_edges[edge_id] = replace(edge, next=following)

    cycles_by_face: dict[int, list[int]] = defaultdict(list)
    visited: set[int] = set()
    for start in range(len(mutable_edges)):
        if start in visited:
            continue
        current = start
        minimum = start
        local: set[int] = set()
        while current not in local:
            if current in visited or current >= len(mutable_edges):
                raise _graph_failure("half-edge cycles overlap or escape graph bounds")
            edge = mutable_edges[current]
            if edge.face != mutable_edges[start].face:
                raise _graph_failure("half-edge cycle changes face")
            local.add(current)
            visited.add(current)
            minimum = min(minimum, current)
            current = edge.next
        if current != start:
            raise _graph_failure("half-edge cycle does not close at its start")
        cycles_by_face[mutable_edges[start].face].append(minimum)

    faces: list[MultiFace] = [
        MultiFace(
            face_id=0,
            palette_index=-1,
            pixel_count=exterior_pixels,
            touches_border=True,
            boundary_cycles=tuple(sorted(cycles_by_face[0])),
            parent_face=None,
            hole_count=max(0, len(cycles_by_face[0]) - 1),
        )
    ]
    for face_id, (palette_index, pixel_count, touches_border) in enumerate(properties, start=1):
        neighbors = {
            pair[1] if pair[0] == face_id else pair[0]: length
            for pair, length in adjacency_lengths.items()
            if face_id in pair
        }
        parent = 0
        if not touches_border and neighbors:
            parent = min(neighbors, key=lambda item: (-neighbors[item], item))
        cycles = tuple(sorted(cycles_by_face[face_id]))
        faces.append(
            MultiFace(
                face_id=face_id,
                palette_index=palette_index,
                pixel_count=pixel_count,
                touches_border=touches_border,
                boundary_cycles=cycles,
                parent_face=parent,
                hole_count=max(0, len(cycles) - 1),
            )
        )

    adjacency = frozenset(pair for pair in adjacency_lengths if pair[0] != 0 and pair[1] != 0)
    graph = MulticolorRegionGraph(
        width=width,
        height=height,
        region_labels=face_labels,
        vertices=tuple(mutable_vertices),
        half_edges=tuple(mutable_edges),
        faces=tuple(faces),
        adjacency=adjacency,
        shared_boundary_lengths=dict(sorted(adjacency_lengths.items())),
        canonical_edge_count=len(mutable_edges) // 2,
    )
    validate_multicolor_region_graph(graph)
    return graph


def validate_multicolor_region_graph(graph: MulticolorRegionGraph) -> None:
    if (
        graph.width < 1
        or graph.height < 1
        or graph.region_labels.shape
        != (
            graph.height,
            graph.width,
        )
    ):
        raise _graph_failure("region graph dimensions are invalid")
    if graph.canonical_edge_count < 0 or len(graph.half_edges) != graph.canonical_edge_count * 2:
        raise _graph_failure("canonical edge count does not match twin pairs")
    if tuple(face.face_id for face in graph.faces) != tuple(range(len(graph.faces))):
        raise _graph_failure("face identifiers are not contiguous")
    canonical_counts = [0] * graph.canonical_edge_count
    predecessor_counts = [0] * len(graph.half_edges)
    adjacency_lengths: dict[tuple[int, int], int] = {}
    outgoing: list[list[int]] = [[] for _ in graph.vertices]
    for index, vertex in enumerate(graph.vertices):
        if (
            vertex.vertex_id != index
            or not 0 <= vertex.position.x <= graph.width
            or not 0 <= vertex.position.y <= graph.height
        ):
            raise _graph_failure("vertex identifiers or coordinates are invalid")
        for edge_id in vertex.outgoing_half_edges:
            if (
                not 0 <= edge_id < len(graph.half_edges)
                or graph.half_edges[edge_id].origin != index
            ):
                raise _graph_failure("vertex outgoing relation is invalid")
    for index, edge in enumerate(graph.half_edges):
        if (
            edge.half_edge_id != index
            or not 0 <= edge.origin < len(graph.vertices)
            or not 0 <= edge.target < len(graph.vertices)
            or not 0 <= edge.twin < len(graph.half_edges)
            or not 0 <= edge.next < len(graph.half_edges)
            or not 0 <= edge.face < len(graph.faces)
            or not 0 <= edge.canonical_edge < graph.canonical_edge_count
            or edge.origin == edge.target
        ):
            raise _graph_failure("half-edge relation is out of range")
        twin = graph.half_edges[edge.twin]
        following = graph.half_edges[edge.next]
        if (
            twin.twin != edge.half_edge_id
            or twin.origin != edge.target
            or twin.target != edge.origin
            or twin.face == edge.face
            or twin.canonical_edge != edge.canonical_edge
        ):
            raise _graph_failure("half-edge twin invariant failed")
        if following.face != edge.face or following.origin != edge.target:
            raise _graph_failure("half-edge next invariant failed")
        canonical_counts[edge.canonical_edge] += 1
        predecessor_counts[edge.next] += 1
        outgoing[edge.origin].append(edge.half_edge_id)
        if edge.half_edge_id < edge.twin:
            pair = (min(edge.face, twin.face), max(edge.face, twin.face))
            adjacency_lengths[pair] = adjacency_lengths.get(pair, 0) + 1
    if any(
        tuple(sorted(edges)) != vertex.outgoing_half_edges
        for edges, vertex in zip(outgoing, graph.vertices, strict=True)
    ):
        raise _graph_failure("vertex outgoing relation is incomplete")
    if any(count != 1 for count in predecessor_counts):
        raise _graph_failure("half-edge predecessor relation is not unique")
    if graph.shared_boundary_lengths != adjacency_lengths:
        raise _graph_failure("shared boundary lengths disagree with canonical edge ownership")
    if graph.adjacency != frozenset(pair for pair in adjacency_lengths if 0 not in pair):
        raise _graph_failure("adjacency disagrees with canonical edge ownership")
    if any(count != 2 for count in canonical_counts):
        raise _graph_failure("canonical edge does not have exactly two half-edges")

    visited: set[int] = set()
    cycle_starts_by_face: dict[int, list[int]] = {index: [] for index in range(len(graph.faces))}
    for start in range(len(graph.half_edges)):
        if start in visited:
            continue
        current = start
        local: set[int] = set()
        while current not in local:
            if current in visited or current >= len(graph.half_edges):
                raise _graph_failure("cycle traversal reused or escaped an edge")
            local.add(current)
            visited.add(current)
            current = graph.half_edges[current].next
        if current != start:
            raise _graph_failure("cycle traversal did not close")
        cycle_starts_by_face[graph.half_edges[start].face].append(min(local))
    for face in graph.faces:
        if tuple(
            sorted(cycle_starts_by_face[face.face_id])
        ) != face.boundary_cycles or face.hole_count != max(0, len(face.boundary_cycles) - 1):
            raise _graph_failure("face boundary cycles disagree with half-edge traversal")
    neighbors: list[set[int]] = [set() for _ in graph.vertices]
    for edge in graph.half_edges:
        neighbors[edge.origin].add(edge.target)
    components = 0
    visited_vertices: set[int] = set()
    for start in range(len(graph.vertices)):
        if start in visited_vertices:
            continue
        components += 1
        stack = [start]
        while stack:
            current = stack.pop()
            if current in visited_vertices:
                continue
            visited_vertices.add(current)
            stack.extend(sorted(neighbors[current] - visited_vertices, reverse=True))
    # Region IDs merge disconnected exterior/hole cells; half-edge boundary
    # cycles, rather than region IDs, are the embedding's planar faces.
    cycle_count = sum(len(starts) for starts in cycle_starts_by_face.values())
    if len(graph.vertices) - graph.canonical_edge_count + cycle_count != 2 * components:
        raise _graph_failure("planar graph Euler invariant failed")
