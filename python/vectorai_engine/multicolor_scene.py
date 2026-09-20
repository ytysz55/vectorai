"""Topology-preserving multicolor scene selection and canonical SVG export."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from pathlib import Path

from vectorai_bench.metrics.editability import measure_svg_editability

from .errors import EngineError, EngineFailure, ErrorCode, Stage
from .multicolor_graph import MulticolorRegionGraph
from .palette import PaletteResult
from .primitives import PrimitiveCandidateSet, extract_face_cycles, recover_closed_primitives
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


def _failure(code: ErrorCode, message: str) -> EngineFailure:
    return EngineFailure(EngineError(code, Stage.MODEL_SELECTION, message))


def _number(value: float, decimals: int = 6) -> str:
    if not math.isfinite(value):
        raise _failure(ErrorCode.EXPORT_FAILED, "SVG coordinate is not finite")
    threshold = 0.5 * 10.0**-decimals
    normalized = 0.0 if abs(value) < threshold else value
    rendered = f"{normalized:.{decimals}f}".rstrip("0").rstrip(".")
    return "0" if rendered == "-0" else rendered


def _path_data(cycles: tuple[tuple[tuple[float, float], ...], ...]) -> str:
    commands: list[str] = []
    for cycle in cycles:
        if len(cycle) < 3:
            raise _failure(
                ErrorCode.EXPORT_FAILED,
                "face boundary cycle has fewer than three points",
            )
        first = cycle[0]
        pieces = [f"M{_number(first[0])} {_number(first[1])}"]
        for point in cycle[1:]:
            pieces.append(f"L{_number(point[0])} {_number(point[1])}")
        pieces.append("Z")
        commands.append(" ".join(pieces))
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
    primitive_error = 0.0
    complexity = 0.0
    for face in graph.faces[1:]:
        if face.palette_index < 0 or face.palette_index >= palette.selected.color_count:
            raise _failure(
                ErrorCode.TOPOLOGY_AMBIGUOUS,
                "region graph palette index does not exist in selected palette",
            )
        cycles = extract_face_cycles(graph, face.face_id)
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
        rectangle = _axis_aligned_rect(face.cycles)
        if rectangle is not None:
            x, y, width, height = rectangle
            lines.append(
                f'  <rect data-face-id="{face.face_id}" '
                f'fill="{_color_hex(color.rgb_srgb)}" x="{_number(x)}" '
                f'y="{_number(y)}" width="{_number(width)}" '
                f'height="{_number(height)}"/>'
            )
        else:
            lines.append(
                f'  <path data-face-id="{face.face_id}" fill="{_color_hex(color.rgb_srgb)}" '
                f'fill-rule="evenodd" d="{_path_data(face.cycles)}"/>'
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
