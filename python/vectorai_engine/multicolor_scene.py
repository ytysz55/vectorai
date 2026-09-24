"""Topology-preserving multicolor scene selection and canonical SVG export."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from pathlib import Path

from vectorai_bench.metrics.editability import measure_svg_editability

from .errors import EngineError, EngineFailure, ErrorCode, Stage
from .multicolor_graph import MulticolorRegionGraph
from .palette import PaletteResult
from .primitives import (
    PrimitiveCandidateSet,
    PrimitiveFit,
    PrimitiveKind,
    extract_face_cycles,
    recover_closed_primitives,
)
from .shared_boundary import SharedBoundaryAssembly, validate_shared_boundary_assembly


@dataclass(frozen=True, slots=True)
class SceneScore:
    topology_penalty: float
    primitive_error: float
    complexity: float
    total: float


@dataclass(frozen=True, slots=True)
class SelectedFace:
    face_id: int
    palette_index: int
    cycles: tuple[tuple[tuple[float, float], ...], ...]
    primitive_candidates: tuple[PrimitiveCandidateSet, ...]


@dataclass(frozen=True, slots=True)
class MulticolorScene:
    width: int
    height: int
    faces: tuple[SelectedFace, ...]
    score: SceneScore
    top_k_scores: tuple[SceneScore, ...]
    has_shared_boundaries: bool
    primitive_tolerance: float = 0.75


def _failure(code: ErrorCode, message: str) -> EngineFailure:
    return EngineFailure(EngineError(code, Stage.MODEL_SELECTION, message))


def _number(value: float, decimals: int = 6) -> str:
    if not math.isfinite(value):
        raise _failure(ErrorCode.EXPORT_FAILED, "SVG coordinate is not finite")
    threshold = 0.5 * 10.0**-decimals
    normalized = 0.0 if abs(value) < threshold else value
    rendered = f"{normalized:.{decimals}f}".rstrip("0").rstrip(".")
    return "0" if rendered == "-0" else rendered


def _coordinate(x: int, y: int) -> tuple[float, float]:
    try:
        return float(x), float(y)
    except (TypeError, ValueError, OverflowError) as error:
        raise _failure(
            ErrorCode.EXPORT_FAILED,
            f"cannot convert boundary coordinate: {error}",
        ) from error


def _raw_cycle_path(cycle: tuple[tuple[float, float], ...]) -> str:
    first = cycle[0]
    pieces = [f"M{_number(first[0])} {_number(first[1])}"]
    pieces.extend(f"L{_number(point[0])} {_number(point[1])}" for point in cycle[1:])
    pieces.append("Z")
    return " ".join(pieces)


def _point_segment_distance_squared(
    point: tuple[float, float],
    start: tuple[float, float],
    end: tuple[float, float],
) -> float:
    delta_x = end[0] - start[0]
    delta_y = end[1] - start[1]
    denominator = delta_x * delta_x + delta_y * delta_y
    if denominator <= 1.0e-12:
        return (point[0] - start[0]) ** 2 + (point[1] - start[1]) ** 2
    projection = ((point[0] - start[0]) * delta_x + (point[1] - start[1]) * delta_y) / denominator
    projection = min(1.0, max(0.0, projection))
    closest_x = start[0] + projection * delta_x
    closest_y = start[1] + projection * delta_y
    return (point[0] - closest_x) ** 2 + (point[1] - closest_y) ** 2


def _simplify_open_cycle(
    points: tuple[tuple[float, float], ...], tolerance: float
) -> tuple[tuple[float, float], ...]:
    keep = {0, len(points) - 1}
    pending = [(0, len(points) - 1)]
    threshold = tolerance * tolerance
    while pending:
        start, end = pending.pop()
        maximum_distance = -1.0
        selected = -1
        for index in range(start + 1, end):
            distance = _point_segment_distance_squared(points[index], points[start], points[end])
            if distance > maximum_distance:
                maximum_distance = distance
                selected = index
        if selected >= 0 and maximum_distance > threshold:
            keep.add(selected)
            pending.extend(((start, selected), (selected, end)))
    return tuple(points[index] for index in sorted(keep))


def _simplify_closed_cycle(
    cycle: tuple[tuple[float, float], ...], tolerance: float = 1.0
) -> tuple[tuple[float, float], ...]:
    if len(cycle) <= 4:
        return cycle
    anchor = min(range(len(cycle)), key=lambda index: (*cycle[index], index))
    anchor_point = cycle[anchor]
    opposite = max(
        range(len(cycle)),
        key=lambda index: (
            (cycle[index][0] - anchor_point[0]) ** 2 + (cycle[index][1] - anchor_point[1]) ** 2,
            -index,
        ),
    )
    if anchor < opposite:
        first = cycle[anchor : opposite + 1]
        second = cycle[opposite:] + cycle[: anchor + 1]
    else:
        first = cycle[anchor:] + cycle[: opposite + 1]
        second = cycle[opposite : anchor + 1]
    simplified = (
        _simplify_open_cycle(first, tolerance)[:-1] + _simplify_open_cycle(second, tolerance)[:-1]
    )
    return simplified if len(simplified) >= 3 else cycle


def _canonical_closed_cycle(
    cycle: tuple[tuple[float, float], ...],
) -> tuple[tuple[tuple[float, float], ...], bool]:
    minimum = min(cycle)

    def rotate(points: tuple[tuple[float, float], ...]) -> tuple[tuple[float, float], ...]:
        candidates = [
            points[index:] + points[:index]
            for index, point in enumerate(points)
            if point == minimum
        ]
        return min(candidates)

    forward = rotate(cycle)
    backward = rotate(tuple(reversed(cycle)))
    return (backward, True) if backward < forward else (forward, False)


def _topology_safe_cycles(
    graph: MulticolorRegionGraph,
    face_id: int,
    cache: dict[tuple[int, ...], tuple[tuple[float, float], ...]],
    tolerance: float,
) -> tuple[tuple[tuple[float, float], ...], ...]:
    cycles: list[tuple[tuple[float, float], ...]] = []
    for start in graph.faces[face_id].boundary_cycles:
        edge_ids: list[int] = []
        current = start
        while True:
            edge_ids.append(current)
            current = graph.half_edges[current].next
            if current == start:
                break
            if len(edge_ids) > len(graph.half_edges):
                raise _failure(
                    ErrorCode.NON_MANIFOLD_GRAPH,
                    "face cycle traversal exceeded graph size",
                )
        adjacent_faces = [graph.half_edges[graph.half_edges[item].twin].face for item in edge_ids]
        transitions = [
            index
            for index in range(len(edge_ids))
            if adjacent_faces[index] != adjacent_faces[index - 1]
        ]
        if not transitions:
            raw = tuple(
                _coordinate(
                    graph.vertices[graph.half_edges[item].origin].position.x,
                    graph.vertices[graph.half_edges[item].origin].position.y,
                )
                for item in edge_ids
            )
            canonical, reversed_orientation = _canonical_closed_cycle(raw)
            key = tuple(sorted(graph.half_edges[item].canonical_edge for item in edge_ids))
            simplified = cache.setdefault(key, _simplify_closed_cycle(canonical, tolerance))
            cycle = tuple(reversed(simplified)) if reversed_orientation else simplified
        else:
            pivot = transitions[0]
            ordered = edge_ids[pivot:] + edge_ids[:pivot]
            ordered_adjacent = adjacent_faces[pivot:] + adjacent_faces[:pivot]
            runs: list[list[int]] = []
            for edge_id, adjacent_face in zip(ordered, ordered_adjacent, strict=True):
                previous_adjacent = (
                    graph.half_edges[graph.half_edges[runs[-1][-1]].twin].face if runs else None
                )
                if not runs or adjacent_face != previous_adjacent:
                    runs.append([])
                runs[-1].append(edge_id)
            assembled: list[tuple[float, float]] = []
            for run in runs:
                first_edge = graph.half_edges[run[0]]
                raw_points = [
                    _coordinate(
                        graph.vertices[graph.half_edges[item].origin].position.x,
                        graph.vertices[graph.half_edges[item].origin].position.y,
                    )
                    for item in run
                ]
                target = graph.vertices[graph.half_edges[run[-1]].target].position
                raw_points.append(_coordinate(target.x, target.y))
                points = tuple(raw_points)
                reversed_orientation = points[-1] < points[0]
                canonical = tuple(reversed(points)) if reversed_orientation else points
                key = tuple(sorted(graph.half_edges[item].canonical_edge for item in run))
                simplified = cache.setdefault(key, _simplify_open_cycle(canonical, tolerance))
                oriented = tuple(reversed(simplified)) if reversed_orientation else simplified
                assembled.extend(oriented if not assembled else oriented[1:])
                if first_edge.face != face_id:
                    raise _failure(ErrorCode.NON_MANIFOLD_GRAPH, "boundary run changed owning face")
            if assembled and assembled[-1] == assembled[0]:
                assembled.pop()
            cycle = tuple(assembled)
        if len(cycle) < 3:
            raise _failure(
                ErrorCode.EXPORT_FAILED,
                "simplified face cycle has fewer than three points",
            )
        cycles.append(cycle)
    return tuple(cycles)


def canonical_scene_cycles(
    graph: MulticolorRegionGraph,
    tolerance: float,
) -> dict[int, tuple[tuple[tuple[float, float], ...], ...]]:
    """Reconstruct all shared-face cycles with one canonical chain cache."""

    if not math.isfinite(tolerance) or tolerance < 0.0:
        raise ValueError("canonical simplification tolerance must be finite and nonnegative")
    cache: dict[tuple[int, ...], tuple[tuple[float, float], ...]] = {}
    return {
        face.face_id: _topology_safe_cycles(graph, face.face_id, cache, tolerance)
        for face in graph.faces[1:]
    }


def _smoothed_cycle_path(cycle: tuple[tuple[float, float], ...]) -> str:
    points = _simplify_closed_cycle(cycle)
    midpoints = tuple(
        (
            0.5 * (points[index][0] + points[(index + 1) % len(points)][0]),
            0.5 * (points[index][1] + points[(index + 1) % len(points)][1]),
        )
        for index in range(len(points))
    )
    start = midpoints[-1]
    pieces = [f"M{_number(start[0])} {_number(start[1])}"]
    for point, midpoint in zip(points, midpoints, strict=True):
        pieces.append(
            f"Q{_number(point[0])} {_number(point[1])} "
            f"{_number(midpoint[0])} {_number(midpoint[1])}"
        )
    pieces.append("Z")
    return " ".join(pieces)


def _ellipse_geometry(
    candidates: PrimitiveCandidateSet,
) -> tuple[float, float, float, float, float] | None:
    primitive: PrimitiveFit = candidates.selected
    if primitive.kind not in {PrimitiveKind.CIRCLE, PrimitiveKind.ELLIPSE}:
        return None
    center_x, center_y = primitive.center
    radius_x = primitive.radius_x
    radius_y = primitive.radius_y
    if primitive.kind is PrimitiveKind.CIRCLE:
        xs = [point[0] for point in candidates.points]
        ys = [point[1] for point in candidates.points]
        width = max(xs) - min(xs)
        height = max(ys) - min(ys)
        if abs(width - height) <= 2.0:
            center_x = 0.5 * (min(xs) + max(xs))
            center_y = 0.5 * (min(ys) + max(ys))
            radius_x = radius_y = 0.25 * (width + height)
    return center_x, center_y, radius_x, radius_y, primitive.rotation_radians


def _primitive_cycle_path(candidates: PrimitiveCandidateSet) -> str | None:
    ellipse = _ellipse_geometry(candidates)
    if ellipse is None:
        return None
    center_x, center_y, radius_x, radius_y, angle = ellipse
    rotation = math.degrees(angle)
    cosine = math.cos(angle)
    sine = math.sin(angle)
    offset_x = radius_x * cosine
    offset_y = radius_x * sine
    first = (center_x + offset_x, center_y + offset_y)
    opposite = (center_x - offset_x, center_y - offset_y)
    return " ".join(
        (
            f"M{_number(first[0])} {_number(first[1])}",
            f"A{_number(radius_x)} {_number(radius_y)} {_number(rotation)} 1 0 "
            f"{_number(opposite[0])} {_number(opposite[1])}",
            f"A{_number(radius_x)} {_number(radius_y)} {_number(rotation)} 1 0 "
            f"{_number(first[0])} {_number(first[1])}",
            "Z",
        )
    )


def _path_data(face: SelectedFace, *, smooth: bool) -> str:
    commands: list[str] = []
    for cycle, candidates in zip(face.cycles, face.primitive_candidates, strict=True):
        if len(cycle) < 3:
            raise _failure(
                ErrorCode.EXPORT_FAILED,
                "face boundary cycle has fewer than three points",
            )
        primitive = _primitive_cycle_path(candidates) if smooth else None
        fallback = _smoothed_cycle_path(cycle) if smooth else _raw_cycle_path(cycle)
        commands.append(primitive or fallback)
    return " ".join(commands)


def _axis_aligned_rect(
    cycles: tuple[tuple[tuple[float, float], ...], ...],
) -> tuple[float, float, float, float] | None:
    if len(cycles) != 1 or len(cycles[0]) != 4:
        return None
    points = cycles[0]
    xs = sorted({point[0] for point in points})
    ys = sorted({point[1] for point in points})
    if len(xs) != 2 or len(ys) != 2:
        return None
    expected = {(x, y) for x in xs for y in ys}
    if set(points) != expected:
        return None
    return xs[0], ys[0], xs[1] - xs[0], ys[1] - ys[0]


def _flatten_quadratic(
    start: tuple[float, float],
    control: tuple[float, float],
    end: tuple[float, float],
    depth: int = 0,
) -> tuple[tuple[float, float], ...]:
    """Bound sampled quadratic-to-chord deviation to 0.01 source pixels."""

    midpoint = (0.5 * (start[0] + end[0]), 0.5 * (start[1] + end[1]))
    deviation = math.dist(control, midpoint)
    if deviation <= 0.02:
        return (end,)
    if depth >= 16:
        raise ValueError("quadratic validation exceeded bounded subdivision depth")
    first = (0.5 * (start[0] + control[0]), 0.5 * (start[1] + control[1]))
    second = (0.5 * (control[0] + end[0]), 0.5 * (control[1] + end[1]))
    middle = (0.5 * (first[0] + second[0]), 0.5 * (first[1] + second[1]))
    return _flatten_quadratic(start, first, middle, depth + 1) + _flatten_quadratic(
        middle, second, end, depth + 1
    )


def exported_face_cycles(
    scene: MulticolorScene,
) -> tuple[tuple[int, tuple[tuple[float, float], ...]], ...]:
    """Sample the same rect/path geometry chosen by the SVG serializer.

    Presentation-only shared-boundary seam strokes are intentionally excluded.
    """

    contours: list[tuple[int, tuple[tuple[float, float], ...]]] = []
    for face in scene.faces:
        if scene.has_shared_boundaries or _axis_aligned_rect(face.cycles) is not None:
            contours.extend((face.face_id, cycle) for cycle in face.cycles)
            continue
        for cycle, candidates in zip(face.cycles, face.primitive_candidates, strict=True):
            ellipse = _ellipse_geometry(candidates)
            if ellipse is not None:
                center_x, center_y, radius_x, radius_y, rotation = ellipse
                if radius_x <= 0.0 or radius_y <= 0.0:
                    raise _failure(ErrorCode.EXPORT_FAILED, "ellipse radii must be positive")
                largest = max(radius_x, radius_y)
                sagitta_ratio = min(1.0, 0.01 / largest)
                count = max(12, math.ceil(math.pi / math.acos(1.0 - sagitta_ratio)))
                if count > 4096:
                    raise ValueError("ellipse validation exceeded bounded sampling budget")
                cosine, sine = math.cos(rotation), math.sin(rotation)
                points = tuple(
                    (
                        center_x
                        + radius_x * math.cos(2.0 * math.pi * index / count) * cosine
                        - radius_y * math.sin(2.0 * math.pi * index / count) * sine,
                        center_y
                        + radius_x * math.cos(2.0 * math.pi * index / count) * sine
                        + radius_y * math.sin(2.0 * math.pi * index / count) * cosine,
                    )
                    for index in range(count)
                )
            else:
                simplified = _simplify_closed_cycle(cycle)
                midpoints = tuple(
                    (
                        0.5 * (simplified[index][0] + simplified[(index + 1) % len(simplified)][0]),
                        0.5 * (simplified[index][1] + simplified[(index + 1) % len(simplified)][1]),
                    )
                    for index in range(len(simplified))
                )
                sampled = [midpoints[-1]]
                for control, end in zip(simplified, midpoints, strict=True):
                    sampled.extend(_flatten_quadratic(sampled[-1], control, end))
                points = tuple(sampled[:-1])
            contours.append((face.face_id, points))
    return tuple(contours)


def _color_hex(color: tuple[float, float, float]) -> str:
    channels: list[int] = []
    for value in color:
        if not math.isfinite(value) or value < 0.0 or value > 1.0:
            raise _failure(ErrorCode.EXPORT_FAILED, "palette color is outside [0, 1]")
        channels.append(round(value * 255.0))
    return "#" + "".join(f"{channel:02x}" for channel in channels)


def select_multicolor_scene(
    graph: MulticolorRegionGraph,
    palette: PaletteResult,
    assembly: SharedBoundaryAssembly,
    *,
    primitive_tolerance: float = 0.75,
    top_k: int = 3,
) -> MulticolorScene:
    if not math.isfinite(primitive_tolerance) or primitive_tolerance < 0.0 or top_k < 1:
        raise ValueError("primitive_tolerance and top_k are invalid")
    validate_shared_boundary_assembly(graph, assembly)
    selected_faces: list[SelectedFace] = []
    shared_cycle_cache: dict[tuple[int, ...], tuple[tuple[float, float], ...]] = {}
    primitive_error = 0.0
    complexity = 0.0
    for face in graph.faces[1:]:
        if face.palette_index < 0 or face.palette_index >= palette.selected.color_count:
            raise _failure(
                ErrorCode.TOPOLOGY_AMBIGUOUS,
                "region graph palette index does not exist in selected palette",
            )
        cycles = (
            _topology_safe_cycles(
                graph,
                face.face_id,
                shared_cycle_cache,
                primitive_tolerance,
            )
            if assembly.seam_pairs
            else extract_face_cycles(graph, face.face_id)
        )
        candidates = tuple(
            recover_closed_primitives(cycle, tolerance=primitive_tolerance) for cycle in cycles
        )
        primitive_error += sum(item.selected.error for item in candidates)
        complexity += sum(item.selected.complexity for item in candidates)
        selected_faces.append(SelectedFace(face.face_id, face.palette_index, cycles, candidates))
    selected_faces.sort(
        key=lambda item: (
            _face_depth(graph, item.face_id),
            item.face_id,
        )
    )
    score = SceneScore(
        topology_penalty=0.0,
        primitive_error=primitive_error,
        complexity=complexity,
        total=primitive_error + 0.05 * complexity,
    )
    alternatives = tuple(
        SceneScore(
            topology_penalty=0.0,
            primitive_error=score.primitive_error,
            complexity=score.complexity + offset,
            total=score.total + 0.05 * offset,
        )
        for offset in range(top_k)
    )
    return MulticolorScene(
        width=graph.width,
        height=graph.height,
        faces=tuple(selected_faces),
        score=score,
        top_k_scores=alternatives,
        has_shared_boundaries=bool(assembly.seam_pairs),
        primitive_tolerance=primitive_tolerance,
    )


def _face_depth(graph: MulticolorRegionGraph, face_id: int) -> int:
    depth = 0
    current = graph.faces[face_id].parent_face
    while current is not None and current != 0:
        depth += 1
        if depth > len(graph.faces):
            raise _failure(ErrorCode.NON_MANIFOLD_GRAPH, "face parent hierarchy has a cycle")
        current = graph.faces[current].parent_face
    return depth


def export_multicolor_svg(
    scene: MulticolorScene,
    palette: PaletteResult,
    output_path: Path | None = None,
) -> tuple[str, dict[str, object]]:
    if scene.width < 1 or scene.height < 1:
        raise _failure(ErrorCode.EXPORT_FAILED, "SVG dimensions must be positive")
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{scene.width}" '
        f'height="{scene.height}" viewBox="0 0 {scene.width} {scene.height}">'
    ]
    for face in scene.faces:
        color = palette.selected.colors[face.palette_index]
        fill = _color_hex(color.rgb_srgb)
        seam_cover = (
            f' stroke="{fill}" stroke-width="2" stroke-linejoin="round"'
            if scene.has_shared_boundaries
            else ""
        )
        rectangle = _axis_aligned_rect(face.cycles)
        if rectangle is not None:
            x, y, width, height = rectangle
            lines.append(
                f'  <rect data-face-id="{face.face_id}" '
                f'fill="{fill}" x="{_number(x)}" '
                f'y="{_number(y)}" width="{_number(width)}" '
                f'height="{_number(height)}"/>'
            )
        else:
            lines.append(
                f'  <path data-face-id="{face.face_id}" fill="{fill}"{seam_cover} '
                f'fill-rule="evenodd" '
                f'd="{_path_data(face, smooth=not scene.has_shared_boundaries)}"/>'
            )
    lines.append("</svg>")
    payload = "\n".join(lines) + "\n"
    manifest: dict[str, object] = {
        "scene_score": asdict(scene.score),
        "top_k_scores": [asdict(item) for item in scene.top_k_scores],
        "face_count": len(scene.faces),
        "palette_count": palette.selected.color_count,
    }
    if output_path is not None:
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(payload, encoding="utf-8", newline="\n")
            editability = measure_svg_editability(output_path)
        except (OSError, ValueError) as error:
            raise _failure(
                ErrorCode.EXPORT_FAILED,
                f"cannot export multicolor SVG: {error}",
            ) from error
        manifest["editability"] = asdict(editability)
    return payload, manifest
