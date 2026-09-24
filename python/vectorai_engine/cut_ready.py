"""Explicit, bounded physical cut-readiness hard gate for trusted stroke scenes."""

from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import islice
from pathlib import Path
from xml.etree import ElementTree

from .stroke_graph import CenterlineGraph
from .stroke_models import StrokeStyle, WidthModel
from .stroke_scene import stroke_export_geometry, validate_cut_outline
from .topology_validation import (
    FindingSeverity,
    TopologyGeometryResult,
    ValidationFinding,
    validate_stroke_output,
)

Point = tuple[float, float]
Segment = tuple[Point, Point]


@dataclass(frozen=True, slots=True)
class CutReadyPolicy:
    physical_width_mm: float
    physical_height_mm: float
    minimum_segment_mm: float = 0.2
    minimum_gap_mm: float = 0.4
    maximum_segments: int = 5000


def _failure(code: str, message: str, *entity_ids: int) -> ValidationFinding:
    return ValidationFinding(code, "cut_ready", FindingSeverity.HARD, message, tuple(entity_ids))


def _result(findings: list[ValidationFinding]) -> TopologyGeometryResult:
    ordered = tuple(
        sorted(set(findings), key=lambda item: (item.code, item.entity_ids, item.message))
    )
    return TopologyGeometryResult(
        valid=not any(item.severity is FindingSeverity.HARD for item in ordered),
        needs_review=False,
        findings=ordered,
    )


def _point_segment_distance_squared(point: Point, segment: Segment) -> float:
    start, end = segment
    dx, dy = end[0] - start[0], end[1] - start[1]
    length_squared = dx * dx + dy * dy
    if length_squared == 0.0:
        return math.dist(point, start) ** 2
    t = max(
        0.0, min(1.0, ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / length_squared)
    )
    projection = (start[0] + t * dx, start[1] + t * dy)
    return math.dist(point, projection) ** 2


def _segment_distance_squared(first: Segment, second: Segment) -> float:
    return min(
        _point_segment_distance_squared(point, other)
        for segment, other in ((first, second), (second, first))
        for point in segment
    )


def validate_cut_ready(
    graph: CenterlineGraph,
    model: WidthModel,
    style: StrokeStyle,
    policy: CutReadyPolicy,
    *,
    generated_svg_path: Path | None = None,
) -> TopologyGeometryResult:
    """Hard-gate generated filled cut contours at an explicit physical scale.

    This is opt-in: normal stroke exports and ambiguous rings remain available,
    but must never be advertised as cut-ready without passing this check.
    """

    findings = list(validate_stroke_output(graph, model, style, cut_outline=True).findings)
    if not graph.edges:
        findings.append(_failure("CUT_READY.EMPTY", "cut job contains no paths"))
        return _result(findings)
    dimensions = (policy.physical_width_mm, policy.physical_height_mm)
    if not all(math.isfinite(value) and 0.0 < value <= 10000.0 for value in dimensions):
        findings.append(
            _failure("CUT_READY.DIMENSIONS", "physical dimensions must be in (0, 10000] mm")
        )
        return _result(findings)
    if (
        not math.isfinite(policy.minimum_segment_mm)
        or not math.isfinite(policy.minimum_gap_mm)
        or policy.minimum_segment_mm <= 0.0
        or policy.minimum_gap_mm <= 0.0
        or not 1 <= policy.maximum_segments <= 50000
    ):
        findings.append(
            _failure("CUT_READY.POLICY", "cut tolerances or segment budget are invalid")
        )
        return _result(findings)
    if graph.width < 1 or graph.height < 1:
        findings.append(_failure("CUT_READY.DIMENSIONS", "raster dimensions must be positive"))
        return _result(findings)
    scale_x = policy.physical_width_mm / graph.width
    scale_y = policy.physical_height_mm / graph.height
    if abs(scale_x - scale_y) > 1.0e-6 * max(scale_x, scale_y):
        findings.append(
            _failure("CUT_READY.UNIFORM_SCALE", "physical sizing must preserve aspect ratio")
        )
        return _result(findings)
    if (
        not math.isfinite(model.constant_width)
        or model.constant_width <= 0.0
        or any(
            not math.isfinite(width) or width <= 0.0
            for edge_widths in model.edge_widths
            for width in edge_widths
        )
    ):
        findings.append(_failure("CUT_READY.POSITIVE_WIDTH", "all stroke widths must be positive"))
        return _result(findings)
    if generated_svg_path is not None:
        valid, errors = validate_cut_outline(generated_svg_path)
        if not valid:
            findings.extend(_failure("CUT_READY.EXPORT", message) for message in errors)
        else:
            try:
                root = ElementTree.fromstring(generated_svg_path.read_bytes())
                svg_size = (root.attrib["width"], root.attrib["height"], root.attrib["viewBox"])
                expected = f"0 0 {graph.width} {graph.height}"
                sized = all(
                    text.endswith("mm") and math.isclose(float(text[:-2]), target, abs_tol=0.00005)
                    for text, target in zip(svg_size[:2], dimensions, strict=True)
                )
                if not sized or svg_size[2] != expected:
                    findings.append(
                        _failure(
                            "CUT_READY.SIZE_EXPORT",
                            "cut SVG physical mm size or pixel viewBox disagrees with policy",
                        )
                    )
            except (OSError, ValueError, KeyError, ElementTree.ParseError) as error:
                findings.append(_failure("CUT_READY.SIZE_EXPORT", f"invalid SVG sizing: {error}"))
    if any(item.severity is FindingSeverity.HARD for item in findings):
        return _result(findings)

    path_segments: list[tuple[int, int, int, Segment]] = []
    for edge_id, points, closed in stroke_export_geometry(graph, model, style, cut_outline=True):
        if not closed or len(points) < 3:
            findings.append(
                _failure("CUT_READY.CLOSURE", "cut outline is not a closed contour", edge_id)
            )
            continue
        # Use exported precision: the cut SVG path uses four decimal places.
        quantized = tuple((round(x, 4), round(y, 4)) for x, y in points)
        if quantized[0] == quantized[-1]:
            quantized = quantized[:-1]
        if len(quantized) < 3:
            findings.append(
                _failure("CUT_READY.CLOSURE", "cut outline collapsed after quantization", edge_id)
            )
            continue
        for index, (first, second) in enumerate(
            zip(quantized, (*quantized[1:], quantized[0]), strict=True)
        ):
            if (
                first[0] < 0.0
                or first[0] > graph.width
                or first[1] < 0.0
                or first[1] > graph.height
                or second[0] < 0.0
                or second[0] > graph.width
                or second[1] < 0.0
                or second[1] > graph.height
            ):
                findings.append(
                    _failure("CUT_READY.BOUNDS", "cut contour exceeds physical canvas", edge_id)
                )
            if math.dist(first, second) * scale_x < policy.minimum_segment_mm:
                findings.append(
                    _failure(
                        "CUT_READY.MIN_SEGMENT",
                        "cut segment is shorter than policy minimum",
                        edge_id,
                    )
                )
            path_segments.append((edge_id, index, len(quantized), (first, second)))
            if len(path_segments) > policy.maximum_segments:
                findings.append(_failure("CUT_READY.BUDGET", "cut geometry exceeds segment budget"))
                return _result(findings)

    gap_px = policy.minimum_gap_mm / scale_x
    ordered = sorted(
        path_segments,
        key=lambda item: (min(item[3][0][0], item[3][1][0]), item[0], item[1]),
    )
    for index, (first_id, first_index, first_count, candidate_first) in enumerate(ordered):
        first_max_x = max(candidate_first[0][0], candidate_first[1][0])
        for second_id, second_index, _, candidate_second in islice(ordered, index + 1, None):
            if min(candidate_second[0][0], candidate_second[1][0]) - first_max_x >= gap_px:
                break
            if first_id == second_id and (
                abs(first_index - second_index) == 1
                or abs(first_index - second_index) == first_count - 1
            ):
                continue
            if _segment_distance_squared(candidate_first, candidate_second) < gap_px * gap_px:
                findings.append(
                    _failure(
                        "CUT_READY.MIN_GAP",
                        "nonadjacent cut segments violate the physical gap minimum",
                        *tuple(sorted({first_id, second_id})),
                    )
                )
    return _result(findings)
