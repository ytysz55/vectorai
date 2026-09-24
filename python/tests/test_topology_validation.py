from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import numpy as np
import pytest
from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

from vectorai_engine.errors import EngineFailure, ErrorCode, Stage
from vectorai_engine.stroke_graph import build_centerline_graph
from vectorai_engine.stroke_models import (
    StrokeCap,
    StrokeJoin,
    StrokeStyle,
    estimate_width_profile,
    select_width_model,
)
from vectorai_engine.topology_validation import (
    GeometryRole,
    TopologyGeometryResult,
    ValidationContour,
    raise_for_validation,
    validate_centerline_graph,
    validate_contours,
    validate_stroke_output,
)
from vectorai_engine.validation_report import geometry_validation_report


def contour(
    entity_id: int,
    points: tuple[tuple[float, float], ...],
    *,
    role: GeometryRole = GeometryRole.FILL_CONTOUR,
    closed: bool = True,
) -> ValidationContour:
    return ValidationContour(entity_id, role, points, closed)


def codes(result: TopologyGeometryResult) -> set[str]:
    return {finding.code for finding in result.findings}


def test_valid_contour_and_opposite_shared_boundary_pass() -> None:
    left = contour(1, ((0.0, 0.0), (5.0, 0.0), (5.0, 5.0), (0.0, 5.0)))
    right = contour(2, ((5.0, 0.0), (10.0, 0.0), (10.0, 5.0), (5.0, 5.0)))

    result = validate_contours(
        (left, right),
        width=10,
        height=5,
        allowed_shared_owners=frozenset({(1, 2)}),
    )

    assert result.valid
    assert result.findings == ()


def test_open_bow_tie_and_duplicate_contours_are_hard_failures() -> None:
    open_fill = contour(1, ((0.0, 0.0), (2.0, 0.0), (1.0, 2.0)), closed=False)
    bow_tie = contour(2, ((1.0, 1.0), (5.0, 5.0), (1.0, 5.0), (5.0, 1.0)))
    duplicate = contour(3, tuple(reversed(bow_tie.points)))

    result = validate_contours((open_fill, bow_tie, duplicate), width=8, height=8)

    assert not result.valid
    assert {
        "GEOMETRY.OPEN_CONTOUR",
        "GEOMETRY.CROSSING",
        "GEOMETRY.DUPLICATE_CONTOUR",
    } <= codes(result)


def test_containment_overlap_rejected_but_declared_hole_is_safe() -> None:
    outer = contour(1, ((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)))
    inside = contour(2, ((2.0, 2.0), (4.0, 2.0), (4.0, 4.0), (2.0, 4.0)))
    overlap = validate_contours((outer, inside), width=10, height=10)
    assert "GEOMETRY.FACE_OVERLAP" in codes(overlap)

    hole = contour(1, tuple(reversed(inside.points)))
    safe = validate_contours(
        (outer, hole, inside),
        width=10,
        height=10,
        allowed_shared_owners=frozenset({(1, 2)}),
    )
    assert safe.valid, safe.findings


def test_partial_collinear_overlap_is_rejected() -> None:
    first = contour(
        1,
        ((1.0, 2.0), (6.0, 2.0)),
        role=GeometryRole.STROKE_CENTERLINE,
        closed=False,
    )
    second = contour(
        2,
        ((4.0, 2.0), (8.0, 2.0)),
        role=GeometryRole.STROKE_CENTERLINE,
        closed=False,
    )

    result = validate_contours((first, second), width=10, height=4)

    assert not result.valid
    assert "GEOMETRY.OVERLAP" in codes(result)


def test_quantization_collapse_and_typed_failure_are_deterministic() -> None:
    collapsed = contour(
        7,
        ((1.0, 1.0), (1.0000001, 1.0), (2.0, 2.0)),
    )
    first = validate_contours((collapsed,), width=4, height=4)
    second = validate_contours((collapsed,), width=4, height=4)

    assert first == second
    assert "GEOMETRY.ZERO_LENGTH_SEGMENT" in codes(first)
    with pytest.raises(EngineFailure) as captured:
        raise_for_validation(first)
    assert captured.value.error.code is ErrorCode.VALIDATION_FAILED
    assert captured.value.error.stage is Stage.VALIDATION
    assert "GEOMETRY.ZERO_LENGTH_SEGMENT" in captured.value.error.context["finding_codes"]


def test_centerline_graph_invariants_accept_line_and_tee() -> None:
    line = np.zeros((32, 48), dtype=np.bool_)
    line[14:19, 5:43] = True
    line_result = validate_centerline_graph(build_centerline_graph(line))

    tee = np.zeros((48, 48), dtype=np.bool_)
    tee[8:42, 22:27] = True
    tee[8:13, 8:40] = True
    tee_result = validate_centerline_graph(build_centerline_graph(tee))

    assert line_result.valid, line_result.findings
    assert tee_result.valid, tee_result.findings


def test_report_is_schema_valid_and_digest_stable() -> None:
    result = validate_contours(
        (contour(1, ((0.0, 0.0), (3.0, 0.0), (3.0, 3.0))),),
        width=4,
        height=4,
    )
    report = geometry_validation_report(
        result, job_id="job-1", source_sha256="a" * 64, svg_bytes=b"<svg/>"
    )
    schema_path = Path(__file__).resolve().parents[2] / "schemas/validation-report.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    cast(Any, Draft202012Validator(schema)).validate(report)
    assert report == geometry_validation_report(
        result, job_id="job-1", source_sha256="a" * 64, svg_bytes=b"<svg/>"
    )


def test_explicitly_closed_ring_is_a_valid_centerline() -> None:
    mask = np.zeros((50, 50), dtype=np.bool_)
    mask[8:42, 8:42] = True
    mask[13:37, 13:37] = False
    graph = build_centerline_graph(mask)

    result = validate_centerline_graph(graph)

    assert result.valid, result.findings
    assert graph.edges[0].start_node == graph.edges[0].end_node


def test_cut_geometry_rejects_self_crossing_ring_but_accepts_line() -> None:
    style = StrokeStyle(StrokeCap.ROUND, StrokeJoin.BEVEL)
    line = np.zeros((50, 80), dtype=np.bool_)
    line[20:29, 8:65] = True
    line_graph = build_centerline_graph(line)
    line_model = select_width_model(estimate_width_profile(line, line_graph), line_graph)
    assert validate_stroke_output(line_graph, line_model, style).valid
    assert validate_stroke_output(line_graph, line_model, style, cut_outline=True).valid

    ring = np.zeros((50, 80), dtype=np.bool_)
    ring[7:43, 12:48] = True
    ring[14:36, 19:41] = False
    ring_graph = build_centerline_graph(ring)
    ring_model = select_width_model(estimate_width_profile(ring, ring_graph), ring_graph)
    cut = validate_stroke_output(ring_graph, ring_model, style, cut_outline=True)
    assert not cut.valid
    assert "GEOMETRY.CROSSING" in codes(cut)


def test_centerline_degree_corruption_is_rejected() -> None:
    mask = np.zeros((32, 48), dtype=np.bool_)
    mask[14:19, 5:43] = True
    graph = build_centerline_graph(mask)
    broken_node = replace(graph.nodes[0], degree=graph.nodes[0].degree + 1)
    broken = replace(graph, nodes=(broken_node, *graph.nodes[1:]))

    result = validate_centerline_graph(broken)

    assert not result.valid
    assert "TOPOLOGY.NODE_DEGREE" in codes(result)
