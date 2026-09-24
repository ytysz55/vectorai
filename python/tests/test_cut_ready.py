from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np

from vectorai_engine.cut_ready import CutReadyPolicy, validate_cut_ready
from vectorai_engine.errors import EngineFailure
from vectorai_engine.stroke_graph import build_centerline_graph
from vectorai_engine.stroke_models import (
    StrokeCap,
    StrokeJoin,
    StrokeStyle,
    estimate_width_profile,
    select_width_model,
)
from vectorai_engine.stroke_scene import export_stroke_svg
from vectorai_engine.topology_validation import TopologyGeometryResult, raise_for_validation


def _stroke(mask: np.ndarray):  # type: ignore[no-untyped-def]
    graph = build_centerline_graph(mask)
    model = select_width_model(estimate_width_profile(mask, graph), graph)
    return graph, model, StrokeStyle(StrokeCap.ROUND, StrokeJoin.BEVEL)


def _codes(result: TopologyGeometryResult) -> set[str]:
    return {item.code for item in result.findings}


def test_cut_ready_positive_line_and_physical_scale(tmp_path: Path) -> None:
    mask = np.zeros((48, 96), dtype=np.bool_)
    mask[20:29, 12:84] = True
    graph, model, style = _stroke(mask)
    path = tmp_path / "cut.svg"
    export_stroke_svg(
        graph,
        model,
        style,
        color="#101010",
        output_path=path,
        cut_outline=True,
        physical_size_mm=(96.0, 48.0),
    )
    policy = CutReadyPolicy(96.0, 48.0)
    valid = validate_cut_ready(graph, model, style, policy, generated_svg_path=path)
    assert valid.valid, valid.findings
    assert valid == validate_cut_ready(graph, model, style, policy, generated_svg_path=path)


def test_cut_ready_rejects_scale_segment_gap_and_stroke(tmp_path: Path) -> None:
    mask = np.zeros((48, 96), dtype=np.bool_)
    mask[20:29, 12:84] = True
    graph, model, style = _stroke(mask)
    policy = CutReadyPolicy(96.0, 48.0)
    wrong_ratio = validate_cut_ready(graph, model, style, replace(policy, physical_height_mm=49.0))
    assert "CUT_READY.UNIFORM_SCALE" in _codes(wrong_ratio)
    too_short = validate_cut_ready(graph, model, style, replace(policy, minimum_segment_mm=100.0))
    assert "CUT_READY.MIN_SEGMENT" in _codes(too_short)
    too_wide_gap = validate_cut_ready(graph, model, style, replace(policy, minimum_gap_mm=100.0))
    assert "CUT_READY.MIN_GAP" in _codes(too_wide_gap)
    path = tmp_path / "cut.svg"
    payload, _ = export_stroke_svg(
        graph,
        model,
        style,
        color="#101010",
        cut_outline=True,
        physical_size_mm=(96.0, 48.0),
    )
    path.write_text(payload.replace('stroke="none"', 'stroke="#101010"'), encoding="utf-8")
    visible = validate_cut_ready(graph, model, style, policy, generated_svg_path=path)
    assert "CUT_READY.EXPORT" in _codes(visible)
    try:
        raise_for_validation(visible)
    except EngineFailure as error:
        assert "CUT_READY.EXPORT" in error.error.context["finding_codes"]
    else:
        raise AssertionError("cut-ready hard failure must raise")


def test_cut_ready_ring_requires_review_not_claimed_as_cut_safe() -> None:
    mask = np.zeros((50, 80), dtype=np.bool_)
    mask[7:43, 12:48] = True
    mask[14:36, 19:41] = False
    graph, model, style = _stroke(mask)
    result = validate_cut_ready(graph, model, style, CutReadyPolicy(80.0, 50.0))
    assert not result.valid
    assert "GEOMETRY.CROSSING" in _codes(result)


def test_cut_ready_rejects_invalid_and_oversized_xml(tmp_path: Path) -> None:
    mask = np.zeros((48, 96), dtype=np.bool_)
    mask[20:29, 12:84] = True
    graph, model, style = _stroke(mask)
    path = tmp_path / "cut.svg"
    path.write_text('<!DOCTYPE svg [<!ENTITY x "boom">]><svg/>', encoding="utf-8")
    result = validate_cut_ready(
        graph, model, style, CutReadyPolicy(96.0, 48.0), generated_svg_path=path
    )
    assert "CUT_READY.EXPORT" in _codes(result)
    path.write_bytes(b"a" * 8_388_609)
    result = validate_cut_ready(
        graph, model, style, CutReadyPolicy(96.0, 48.0), generated_svg_path=path
    )
    assert "CUT_READY.EXPORT" in _codes(result)
