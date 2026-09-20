"""Explicit topology hypotheses for ambiguous multicolor grid junctions."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .multicolor_graph import MulticolorRegionGraph
from .segmentation import SpatialSegmentation


class JunctionKind(StrEnum):
    CHECKERBOARD = "checkerboard"
    T_JUNCTION = "t_junction"
    MULTIWAY = "multiway"


@dataclass(frozen=True, slots=True)
class JunctionAlternative:
    name: str
    continuation_faces: tuple[int, ...]
    score: float


@dataclass(frozen=True, slots=True)
class JunctionHypothesis:
    vertex_id: int
    kind: JunctionKind
    incident_faces: tuple[int, ...]
    alternatives: tuple[JunctionAlternative, ...]
    selected_index: int
    confidence: float
    requires_review: bool


def _face_at(graph: MulticolorRegionGraph, x: int, y: int) -> int:
    if x < 0 or y < 0 or x >= graph.width or y >= graph.height:
        return 0
    try:
        return int(graph.region_labels[y, x])
    except (TypeError, ValueError, OverflowError, IndexError):
        return 0


def _palette_at(segmentation: SpatialSegmentation, x: int, y: int) -> int:
    if x < 0 or y < 0 or x >= segmentation.labels.shape[1] or y >= segmentation.labels.shape[0]:
        return -1
    try:
        return int(segmentation.labels[y, x])
    except (TypeError, ValueError, OverflowError, IndexError):
        return -1


def _local_confidence(segmentation: SpatialSegmentation, x: int, y: int) -> float:
    values: list[float] = []
    for pixel_x, pixel_y in ((x - 1, y - 1), (x, y - 1), (x, y), (x - 1, y)):
        if (
            0 <= pixel_x < segmentation.labels.shape[1]
            and 0 <= pixel_y < segmentation.labels.shape[0]
        ):
            try:
                values.append(float(segmentation.confidence[pixel_y, pixel_x]))
            except (TypeError, ValueError, OverflowError, IndexError):
                continue
    return sum(values) / len(values) if values else 0.0


def analyze_junction_hypotheses(
    graph: MulticolorRegionGraph,
    segmentation: SpatialSegmentation,
    *,
    review_threshold: float = 0.65,
) -> tuple[JunctionHypothesis, ...]:
    if not 0.0 <= review_threshold <= 1.0:
        raise ValueError("review_threshold must be in [0, 1]")
    if segmentation.labels.shape != graph.region_labels.shape:
        raise ValueError("segmentation and graph dimensions must match")
    hypotheses: list[JunctionHypothesis] = []
    for vertex in graph.vertices:
        if len(vertex.outgoing_half_edges) <= 2:
            continue
        x = vertex.position.x
        y = vertex.position.y
        if x == 0 or y == 0 or x == graph.width or y == graph.height:
            continue
        quadrants = (
            _face_at(graph, x - 1, y - 1),
            _face_at(graph, x, y - 1),
            _face_at(graph, x, y),
            _face_at(graph, x - 1, y),
        )
        palette_quadrants = (
            _palette_at(segmentation, x - 1, y - 1),
            _palette_at(segmentation, x, y - 1),
            _palette_at(segmentation, x, y),
            _palette_at(segmentation, x - 1, y),
        )
        incident = tuple(sorted(set(quadrants)))
        palette_values = tuple(sorted(set(palette_quadrants)))
        counts = {palette: palette_quadrants.count(palette) for palette in palette_values}
        local_confidence = _local_confidence(segmentation, x, y)
        alternatives: tuple[JunctionAlternative, ...]
        checkerboard = (
            palette_quadrants[0] == palette_quadrants[2]
            and palette_quadrants[1] == palette_quadrants[3]
            and palette_quadrants[0] != palette_quadrants[1]
        )
        if checkerboard:
            first_faces = tuple(sorted({quadrants[0], quadrants[2]}))
            second_faces = tuple(sorted({quadrants[1], quadrants[3]}))
            alternatives = (
                JunctionAlternative("northwest_southeast", first_faces, 0.5),
                JunctionAlternative("northeast_southwest", second_faces, 0.5),
            )
            kind = JunctionKind.CHECKERBOARD
            confidence = min(0.5, local_confidence)
        elif len(palette_values) == 3 and sorted(counts.values()) == [1, 1, 2]:
            dominant_palette = min(
                (palette for palette, count in counts.items() if count == 2),
                default=palette_values[0],
            )
            dominant_faces = tuple(
                sorted(
                    {
                        face
                        for face, palette in zip(quadrants, palette_quadrants, strict=True)
                        if palette == dominant_palette
                    }
                )
            )
            other_faces = tuple(face for face in incident if face not in dominant_faces)
            primary_score = 0.5 + 0.5 * local_confidence
            alternatives = (
                JunctionAlternative("dominant_continues", dominant_faces, primary_score),
                JunctionAlternative("minor_faces_continue", other_faces, 1.0 - primary_score),
            )
            kind = JunctionKind.T_JUNCTION
            confidence = primary_score
        elif len(palette_values) >= 3:
            alternatives = tuple(
                JunctionAlternative(
                    f"face_{face}_continues",
                    (face,),
                    local_confidence / max(len(incident), 1),
                )
                for face in incident
            )
            kind = JunctionKind.MULTIWAY
            confidence = local_confidence / max(len(incident), 1)
        else:
            continue
        alternatives = tuple(sorted(alternatives, key=lambda item: (-item.score, item.name)))
        selected = 0
        hypotheses.append(
            JunctionHypothesis(
                vertex_id=vertex.vertex_id,
                kind=kind,
                incident_faces=incident,
                alternatives=alternatives,
                selected_index=selected,
                confidence=confidence,
                requires_review=confidence < review_threshold,
            )
        )
    return tuple(sorted(hypotheses, key=lambda item: item.vertex_id))
