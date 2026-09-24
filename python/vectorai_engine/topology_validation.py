"""Deterministic topology and geometry validation over trusted scene models."""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from itertools import chain, islice, pairwise

from .errors import EngineError, EngineFailure, ErrorCode, Stage
from .multicolor_graph import MulticolorRegionGraph, validate_multicolor_region_graph
from .multicolor_scene import MulticolorScene, canonical_scene_cycles, exported_face_cycles
from .shared_boundary import SharedBoundaryAssembly, validate_shared_boundary_assembly
from .stroke_graph import CenterlineGraph, StrokeNodeKind
from .stroke_models import StrokeStyle, WidthModel, WidthModelKind
from .stroke_scene import stroke_export_geometry

Point = tuple[float, float]
QuantizedPoint = tuple[int, int]
Segment = tuple[QuantizedPoint, QuantizedPoint]


class GeometryRole(StrEnum):
    FILL_CONTOUR = "fill_contour"
    STROKE_CENTERLINE = "stroke_centerline"
    CUT_OUTLINE = "cut_outline"


class FindingSeverity(StrEnum):
    HARD = "hard"
    SOFT = "soft"


@dataclass(frozen=True, slots=True)
class ValidationContour:
    entity_id: int
    role: GeometryRole
    points: tuple[Point, ...]
    closed: bool


@dataclass(frozen=True, slots=True)
class ValidationFinding:
    code: str
    category: str
    severity: FindingSeverity
    message: str
    entity_ids: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class TopologyGeometryResult:
    valid: bool
    needs_review: bool
    findings: tuple[ValidationFinding, ...]


def _finding(
    code: str,
    category: str,
    message: str,
    *entity_ids: int,
    severity: FindingSeverity = FindingSeverity.HARD,
) -> ValidationFinding:
    return ValidationFinding(
        code,
        category,
        severity,
        message,
        tuple(sorted(set(entity_ids))),
    )


def _result(findings: Iterable[ValidationFinding]) -> TopologyGeometryResult:
    ordered = tuple(
        sorted(
            set(findings),
            key=lambda item: (
                item.code,
                item.entity_ids,
                item.severity.value,
                item.message,
            ),
        )
    )
    hard = any(item.severity is FindingSeverity.HARD for item in ordered)
    soft = any(item.severity is FindingSeverity.SOFT for item in ordered)
    return TopologyGeometryResult(not hard, soft and not hard, ordered)


def raise_for_validation(result: TopologyGeometryResult) -> None:
    """Raise one typed hard failure while preserving deterministic finding codes."""

    hard = tuple(item for item in result.findings if item.severity is FindingSeverity.HARD)
    if not hard:
        return
    entity_ids = sorted({entity_id for item in hard for entity_id in item.entity_ids})
    raise EngineFailure(
        EngineError(
            ErrorCode.VALIDATION_FAILED,
            Stage.VALIDATION,
            hard[0].message,
            entity_ids=tuple(entity_ids),
            context={"finding_codes": ",".join(item.code for item in hard)},
        )
    )


def _quantize(point: Point, scale: int) -> QuantizedPoint:
    return (round(point[0] * scale), round(point[1] * scale))


def _segments(points: tuple[QuantizedPoint, ...], closed: bool) -> tuple[Segment, ...]:
    values = tuple(pairwise(points))
    if closed and len(points) > 1:
        values += ((points[-1], points[0]),)
    return values


def _segment_key(segment: Segment) -> Segment:
    first, second = segment
    return (first, second) if first <= second else (second, first)


def _canonical_contour(points: tuple[QuantizedPoint, ...]) -> tuple[QuantizedPoint, ...]:
    if not points:
        return ()

    def rotations(values: tuple[QuantizedPoint, ...]) -> Iterable[tuple[QuantizedPoint, ...]]:
        for index in range(len(values)):
            yield values[index:] + values[:index]

    return min(chain(rotations(points), rotations(tuple(reversed(points)))))


def _orientation(first: QuantizedPoint, second: QuantizedPoint, third: QuantizedPoint) -> int:
    value = (second[0] - first[0]) * (third[1] - first[1]) - (second[1] - first[1]) * (
        third[0] - first[0]
    )
    return (value > 0) - (value < 0)


def _on_segment(first: QuantizedPoint, point: QuantizedPoint, second: QuantizedPoint) -> bool:
    return (
        _orientation(first, point, second) == 0
        and min(first[0], second[0]) <= point[0] <= max(first[0], second[0])
        and min(first[1], second[1]) <= point[1] <= max(first[1], second[1])
    )


def _intersection_kind(first: Segment, second: Segment) -> str | None:
    a, b = first
    c, d = second
    first_c = _orientation(a, b, c)
    first_d = _orientation(a, b, d)
    second_a = _orientation(c, d, a)
    second_b = _orientation(c, d, b)
    if first_c * first_d < 0 and second_a * second_b < 0:
        return "crossing"
    contacts = {
        point
        for point, lies_on in (
            (c, _on_segment(a, c, b)),
            (d, _on_segment(a, d, b)),
            (a, _on_segment(c, a, d)),
            (b, _on_segment(c, b, d)),
        )
        if lies_on
    }
    if not contacts:
        return None
    if first_c == 0 and first_d == 0 and second_a == 0 and second_b == 0 and len(contacts) >= 2:
        return "overlap"
    return "endpoint"


def _point_in_cycle(point: QuantizedPoint, cycle: tuple[QuantizedPoint, ...]) -> bool | None:
    """Return None on the boundary; otherwise even-odd containment."""

    inside = False
    for first, second in _segments(cycle, True):
        if _on_segment(first, point, second):
            return None
        if (first[1] > point[1]) == (second[1] > point[1]):
            continue
        cross = (point[0] - first[0]) * (second[1] - first[1])
        threshold = (second[0] - first[0]) * (point[1] - first[1])
        if (cross < threshold) == (second[1] > first[1]):
            inside = not inside
    return inside


def validate_contours(
    contours: tuple[ValidationContour, ...],
    *,
    width: int,
    height: int,
    coordinate_decimals: int = 6,
    allowed_shared_owners: frozenset[tuple[int, int]] = frozenset(),
    canvas_margin: float = 0.0,
) -> TopologyGeometryResult:
    """Validate quantized polygon/centerline geometry without parsing SVG."""

    findings: list[ValidationFinding] = []
    scale = 10**coordinate_decimals
    quantized: list[tuple[ValidationContour, tuple[QuantizedPoint, ...], tuple[Segment, ...]]] = []
    contour_signatures: dict[tuple[QuantizedPoint, ...], int] = {}
    segment_owners: dict[Segment, list[tuple[int, Segment]]] = {}

    for contour in sorted(contours, key=lambda item: (item.entity_id, item.role.value)):
        if contour.role is not GeometryRole.STROKE_CENTERLINE and not contour.closed:
            findings.append(
                _finding(
                    "GEOMETRY.OPEN_CONTOUR",
                    "geometry",
                    "filled and cut contours must be closed",
                    contour.entity_id,
                )
            )
        minimum = 3 if contour.closed else 2
        if len(contour.points) < minimum:
            findings.append(
                _finding(
                    "GEOMETRY.MINIMUM_POINTS",
                    "geometry",
                    "contour has too few points",
                    contour.entity_id,
                )
            )
            continue
        if any(
            not math.isfinite(value)
            or point[0] < -canvas_margin
            or point[1] < -canvas_margin
            or point[0] > width + canvas_margin
            or point[1] > height + canvas_margin
            for point in contour.points
            for value in point
        ):
            findings.append(
                _finding(
                    "GEOMETRY.COORDINATE_DOMAIN",
                    "geometry",
                    "contour coordinate is non-finite or outside the canvas",
                    contour.entity_id,
                )
            )
            continue
        points = tuple(_quantize(point, scale) for point in contour.points)
        if contour.closed and len(points) > 1 and points[-1] == points[0]:
            points = points[:-1]
        segments = _segments(points, contour.closed)
        if any(first == second for first, second in segments):
            findings.append(
                _finding(
                    "GEOMETRY.ZERO_LENGTH_SEGMENT",
                    "geometry",
                    "contour contains a zero-length segment after quantization",
                    contour.entity_id,
                )
            )
        signature = (
            _canonical_contour(points) if contour.closed else min(points, tuple(reversed(points)))
        )
        previous = contour_signatures.get(signature)
        shared_twin = (
            previous is not None
            and previous != contour.entity_id
            and tuple(sorted((previous, contour.entity_id))) in allowed_shared_owners
            and contour.role is GeometryRole.FILL_CONTOUR
        )
        if previous is not None and not shared_twin:
            findings.append(
                _finding(
                    "GEOMETRY.DUPLICATE_CONTOUR",
                    "geometry",
                    "duplicate contour geometry",
                    previous,
                    contour.entity_id,
                )
            )
        elif previous is None:
            contour_signatures[signature] = contour.entity_id
        local_segments: set[Segment] = set()
        for segment in segments:
            key = _segment_key(segment)
            if key in local_segments:
                findings.append(
                    _finding(
                        "GEOMETRY.DUPLICATE_SEGMENT",
                        "geometry",
                        "contour repeats an undirected segment",
                        contour.entity_id,
                    )
                )
            local_segments.add(key)
            segment_owners.setdefault(key, []).append((contour.entity_id, segment))
        quantized.append((contour, points, segments))

    for owners in segment_owners.values():
        if len(owners) < 2:
            continue
        owner_ids = tuple(sorted({owner for owner, _ in owners}))
        pair = (owner_ids[0], owner_ids[-1]) if len(owner_ids) == 2 else None
        opposite = len(owners) == 2 and owners[0][1] == tuple(reversed(owners[1][1]))
        if pair not in allowed_shared_owners or not opposite or len(owner_ids) != 2:
            findings.append(
                _finding(
                    "GEOMETRY.OVERLAP",
                    "geometry",
                    "segment ownership overlaps without an opposite shared-boundary pair",
                    *owner_ids,
                )
            )

    records: list[tuple[int, int, Segment]] = []
    for contour_index, (_, _, segments) in enumerate(quantized):
        records.extend(
            (contour_index, segment_index, segment)
            for segment_index, segment in enumerate(segments)
            if segment[0] != segment[1]
        )
    records.sort(
        key=lambda item: (
            min(item[2][0][0], item[2][1][0]),
            min(item[2][0][1], item[2][1][1]),
            item[0],
            item[1],
        )
    )
    for left_index, (first_contour, first_segment_index, first) in enumerate(records):
        first_max_x = max(first[0][0], first[1][0])
        for second_contour, second_segment_index, second in islice(records, left_index + 1, None):
            if min(second[0][0], second[1][0]) > first_max_x:
                break
            if _segment_key(first) == _segment_key(second):
                continue
            first_meta, _, first_segments = quantized[first_contour]
            second_meta, _, _ = quantized[second_contour]
            if first_contour == second_contour:
                separation = abs(first_segment_index - second_segment_index)
                adjacent = separation == 1 or (
                    first_meta.closed and separation == len(first_segments) - 1
                )
                if adjacent:
                    continue
            kind = _intersection_kind(first, second)
            if kind not in {"crossing", "overlap"}:
                continue
            code = "GEOMETRY.CROSSING" if kind == "crossing" else "GEOMETRY.OVERLAP"
            findings.append(
                _finding(
                    code,
                    "geometry",
                    f"contours have an undeclared {kind}",
                    first_meta.entity_id,
                    second_meta.entity_id,
                )
            )

    filled: dict[int, list[tuple[QuantizedPoint, ...]]] = {}
    for contour, points, _ in quantized:
        if contour.role is GeometryRole.FILL_CONTOUR and contour.closed:
            filled.setdefault(contour.entity_id, []).append(points)
    for first_id in sorted(filled):
        for second_id in sorted(item for item in filled if item > first_id):
            for owner, target in ((first_id, second_id), (second_id, first_id)):
                overlap = False
                for inner_cycle in filled[owner]:
                    for point in inner_cycle:
                        tests = [_point_in_cycle(point, outer) for outer in filled[target]]
                        if (
                            all(value is not None for value in tests)
                            and sum(bool(value) for value in tests) % 2 == 1
                        ):
                            overlap = True
                            break
                    if overlap:
                        break
                if overlap:
                    findings.append(
                        _finding(
                            "GEOMETRY.FACE_OVERLAP",
                            "geometry",
                            "filled faces overlap by containment",
                            first_id,
                            second_id,
                        )
                    )
                    break

    return _result(findings)


def validate_multicolor_output(
    graph: MulticolorRegionGraph,
    assembly: SharedBoundaryAssembly,
    scene: MulticolorScene,
) -> TopologyGeometryResult:
    findings: list[ValidationFinding] = []
    try:
        validate_multicolor_region_graph(graph)
    except EngineFailure as error:
        findings.append(_finding("TOPOLOGY.GRAPH_INVARIANTS", "topology", error.error.message))
        return _result(findings)
    try:
        validate_shared_boundary_assembly(graph, assembly)
    except EngineFailure as error:
        findings.append(_finding("TOPOLOGY.SHARED_BOUNDARY", "topology", error.error.message))
    if (scene.width, scene.height) != (graph.width, graph.height):
        findings.append(
            _finding(
                "TOPOLOGY.SCENE_DIMENSIONS",
                "topology",
                "scene canvas dimensions disagree with region graph",
            )
        )
    expected_faces = tuple(range(1, len(graph.faces)))
    selected_faces = tuple(face.face_id for face in scene.faces)
    if tuple(sorted(selected_faces)) != expected_faces:
        findings.append(
            _finding(
                "TOPOLOGY.FACE_OWNERSHIP",
                "topology",
                "scene faces are not contiguous graph face identifiers",
                *selected_faces,
            )
        )
        return _result(findings)
    if scene.has_shared_boundaries:
        if not math.isfinite(scene.primitive_tolerance) or scene.primitive_tolerance < 0.0:
            findings.append(
                _finding(
                    "TOPOLOGY.CANONICAL_PROVENANCE",
                    "topology",
                    "canonical simplification tolerance is invalid",
                )
            )
            return _result(findings)
        expected_cycles = canonical_scene_cycles(graph, scene.primitive_tolerance)
        by_face = {face.face_id: face for face in scene.faces}
        for face in graph.faces[1:]:
            if by_face[face.face_id].cycles != expected_cycles[face.face_id]:
                findings.append(
                    _finding(
                        "GEOMETRY.SHARED_BOUNDARY_GAP",
                        "geometry",
                        "scene cycle differs from canonical graph-owned boundary geometry",
                        face.face_id,
                    )
                )
        if findings:
            return _result(findings)
    contours = tuple(
        ValidationContour(face.face_id, GeometryRole.FILL_CONTOUR, cycle, True)
        for face in scene.faces
        for cycle in face.cycles
    )
    contour_result = validate_contours(
        contours,
        width=scene.width,
        height=scene.height,
        allowed_shared_owners=graph.adjacency,
    )
    findings.extend(contour_result.findings)
    if not contour_result.valid:
        return _result(findings)
    if not scene.has_shared_boundaries:
        try:
            exported = tuple(
                ValidationContour(face_id, GeometryRole.FILL_CONTOUR, points, True)
                for face_id, points in exported_face_cycles(scene)
            )
        except (ValueError, OverflowError, EngineFailure) as error:
            findings.append(
                _finding(
                    "GEOMETRY.EXPORT_SAMPLING",
                    "geometry",
                    f"cannot bound exported path geometry: {error}",
                )
            )
            return _result(findings)
        exported_result = validate_contours(
            exported,
            width=scene.width,
            height=scene.height,
            canvas_margin=max(scene.width, scene.height),
        )
        findings.extend(exported_result.findings)
        if not exported_result.valid:
            return _result(findings)

    observed_shared: set[tuple[int, int]] = set()
    owner_by_segment: dict[Segment, list[tuple[int, Segment]]] = {}
    for contour in contours:
        points = tuple(_quantize(point, 1_000_000) for point in contour.points)
        for segment in _segments(points, True):
            owner_by_segment.setdefault(_segment_key(segment), []).append(
                (contour.entity_id, segment)
            )
    for owners in owner_by_segment.values():
        if len(owners) == 2 and owners[0][1] == tuple(reversed(owners[1][1])):
            first_owner, second_owner = sorted((owners[0][0], owners[1][0]))
            observed_shared.add((first_owner, second_owner))
    for pair in sorted(graph.adjacency - observed_shared):
        findings.append(
            _finding(
                "GEOMETRY.SHARED_BOUNDARY_GAP",
                "geometry",
                "declared adjacent faces do not share reversed scene geometry",
                *pair,
            )
        )
    return _result(findings)


def validate_stroke_output(
    graph: CenterlineGraph,
    model: WidthModel,
    style: StrokeStyle,
    *,
    cut_outline: bool = False,
) -> TopologyGeometryResult:
    """Validate generated normal paths or closed cut outlines, not arbitrary SVG."""

    graph_result = validate_centerline_graph(graph)
    if not graph_result.valid:
        return graph_result
    filled = cut_outline or model.kind is WidthModelKind.VARIABLE
    geometry = stroke_export_geometry(graph, model, style, cut_outline=cut_outline)
    contours = tuple(
        ValidationContour(
            edge_id,
            GeometryRole.CUT_OUTLINE
            if cut_outline
            else GeometryRole.FILL_CONTOUR
            if filled
            else GeometryRole.STROKE_CENTERLINE,
            points,
            closed,
        )
        for edge_id, points, closed in geometry
    )
    exported_result = validate_contours(
        contours,
        width=graph.width,
        height=graph.height,
        coordinate_decimals=4,
        canvas_margin=max(graph.width, graph.height),
    )
    return _result((*graph_result.findings, *exported_result.findings))


def validate_centerline_graph(graph: CenterlineGraph) -> TopologyGeometryResult:
    findings: list[ValidationFinding] = []
    if graph.width < 1 or graph.height < 1 or graph.skeleton.shape != (graph.height, graph.width):
        findings.append(
            _finding(
                "TOPOLOGY.GRAPH_DIMENSIONS",
                "topology",
                "centerline graph dimensions are invalid",
            )
        )
        return _result(findings)
    incident = [0] * len(graph.nodes)
    if graph.removed_spur_count < 0:
        findings.append(
            _finding(
                "TOPOLOGY.SPURS",
                "topology",
                "removed spur count cannot be negative",
            )
        )
    edge_signatures: dict[tuple[tuple[int, int], ...], int] = {}
    adjacency: list[set[int]] = [set() for _ in graph.nodes]
    contours: list[ValidationContour] = []
    for index, node in enumerate(graph.nodes):
        if node.node_id != index or not (
            0 <= node.point.x < graph.width and 0 <= node.point.y < graph.height
        ):
            findings.append(
                _finding(
                    "TOPOLOGY.NODE_IDS",
                    "topology",
                    "stroke node identifiers are not contiguous",
                    node.node_id,
                )
            )
    for index, edge in enumerate(graph.edges):
        if edge.edge_id != index or not (
            0 <= edge.start_node < len(graph.nodes) and 0 <= edge.end_node < len(graph.nodes)
        ):
            findings.append(
                _finding(
                    "TOPOLOGY.EDGE_RELATION",
                    "topology",
                    "stroke edge relation is invalid",
                    edge.edge_id,
                )
            )
            continue
        if len(edge.points) < 2 or edge.length <= 0.0 or not math.isfinite(edge.length):
            findings.append(
                _finding(
                    "GEOMETRY.EDGE_LENGTH",
                    "geometry",
                    "stroke edge has invalid points or length",
                    edge.edge_id,
                )
            )
            continue
        measured_length = sum(
            math.hypot(second.x - first.x, second.y - first.y)
            for first, second in pairwise(edge.points)
        )
        if not math.isclose(edge.length, measured_length, abs_tol=1.0e-6):
            findings.append(
                _finding(
                    "GEOMETRY.EDGE_LENGTH",
                    "geometry",
                    "stored stroke length disagrees with centerline points",
                    edge.edge_id,
                )
            )
        if (
            edge.points[0] != graph.nodes[edge.start_node].point
            or edge.points[-1] != graph.nodes[edge.end_node].point
        ):
            findings.append(
                _finding(
                    "TOPOLOGY.EDGE_ENDPOINTS",
                    "topology",
                    "stroke edge endpoints disagree with graph nodes",
                    edge.edge_id,
                )
            )
        incident[edge.start_node] += 1
        incident[edge.end_node] += 1
        adjacency[edge.start_node].add(edge.end_node)
        adjacency[edge.end_node].add(edge.start_node)
        signature = tuple((point.x, point.y) for point in edge.points)
        canonical = min(signature, tuple(reversed(signature)))
        previous = edge_signatures.get(canonical)
        if previous is not None:
            findings.append(
                _finding(
                    "GEOMETRY.DUPLICATE_CENTERLINE",
                    "geometry",
                    "duplicate stroke centerline",
                    previous,
                    edge.edge_id,
                )
            )
        else:
            edge_signatures[canonical] = edge.edge_id
        contours.append(
            ValidationContour(
                edge.edge_id,
                GeometryRole.STROKE_CENTERLINE,
                tuple((point.x, point.y) for point in edge.points),
                edge.start_node == edge.end_node,
            )
        )
    for index, node in enumerate(graph.nodes):
        if incident[index] != node.degree:
            findings.append(
                _finding(
                    "TOPOLOGY.NODE_DEGREE",
                    "topology",
                    "stored stroke degree disagrees with edge incidence",
                    node.node_id,
                )
            )
        expected = (
            StrokeNodeKind.ENDPOINT
            if node.degree == 1
            else StrokeNodeKind.JUNCTION
            if node.degree > 2
            else StrokeNodeKind.CYCLE
        )
        if node.kind is not expected:
            findings.append(
                _finding(
                    "TOPOLOGY.NODE_KIND",
                    "topology",
                    "stroke node kind disagrees with degree",
                    node.node_id,
                )
            )
    visited: set[int] = set()
    components = 0
    for start in range(len(graph.nodes)):
        if start in visited:
            continue
        components += 1
        stack = [start]
        while stack:
            current = stack.pop()
            if current in visited:
                continue
            visited.add(current)
            stack.extend(sorted(adjacency[current] - visited, reverse=True))
    if components != graph.component_count:
        findings.append(
            _finding(
                "TOPOLOGY.COMPONENT_COUNT",
                "topology",
                "stored stroke component count disagrees with graph traversal",
            )
        )
    contour_result = validate_contours(
        tuple(contours),
        width=graph.width,
        height=graph.height,
        coordinate_decimals=4,
    )
    findings.extend(contour_result.findings)
    return _result(findings)
