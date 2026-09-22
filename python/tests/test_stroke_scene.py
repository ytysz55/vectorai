from __future__ import annotations

from pathlib import Path

import numpy as np

from vectorai_engine.stroke_graph import build_centerline_graph
from vectorai_engine.stroke_models import (
    StrokeCap,
    StrokeJoin,
    StrokeStyle,
    estimate_width_profile,
    select_width_model,
)
from vectorai_engine.stroke_scene import export_stroke_svg, validate_cut_outline


def test_stroke_and_cut_outline_export_are_explicit_and_deterministic(tmp_path: Path) -> None:
    mask = np.zeros((48, 96), dtype=np.bool_)
    mask[20:29, 12:84] = True
    graph = build_centerline_graph(mask)
    model = select_width_model(estimate_width_profile(mask, graph), graph)
    style = StrokeStyle(StrokeCap.ROUND, StrokeJoin.BEVEL)

    first, manifest = export_stroke_svg(graph, model, style, color="#111827")
    second, second_manifest = export_stroke_svg(graph, model, style, color="#111827")
    assert first == second
    assert manifest == second_manifest
    assert 'stroke-linecap="round"' in first
    assert 'stroke-linejoin="bevel"' in first
    assert 'fill="none"' in first

    cut_path = tmp_path / "cut.svg"
    cut_payload, _ = export_stroke_svg(
        graph,
        model,
        style,
        color="#111827",
        output_path=cut_path,
        cut_outline=True,
    )
    assert 'stroke="none"' in cut_payload
    assert cut_payload.count("Z") == len(graph.edges)
    assert validate_cut_outline(cut_path) == (True, ())
