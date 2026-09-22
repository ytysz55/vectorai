from __future__ import annotations

import numpy as np

from vectorai_engine.stroke_graph import build_centerline_graph
from vectorai_engine.stroke_models import (
    StrokeCap,
    StrokeJoin,
    WidthModelKind,
    estimate_width_profile,
    select_width_model,
    style_candidates,
)


def test_constant_and_variable_width_models() -> None:
    constant = np.zeros((64, 112), dtype=np.bool_)
    constant[28:37, 12:100] = True
    constant_graph = build_centerline_graph(constant)
    constant_profile = estimate_width_profile(constant, constant_graph)
    constant_model = select_width_model(constant_profile, constant_graph)
    assert constant_model.kind is WidthModelKind.CONSTANT
    assert constant_model.constant_width == 9.0

    variable = np.zeros((64, 112), dtype=np.bool_)
    for x in range(12, 100):
        half_width = 3 + (x - 12) // 14
        variable[32 - half_width : 33 + half_width, x] = True
    variable_graph = build_centerline_graph(variable)
    variable_profile = estimate_width_profile(variable, variable_graph)
    variable_model = select_width_model(variable_profile, variable_graph)
    assert variable_model.kind is WidthModelKind.VARIABLE
    assert variable_profile.maximum_width > variable_profile.minimum_width


def test_style_candidates_cover_all_cap_join_pairs() -> None:
    candidates = style_candidates()
    assert len(candidates) == 9
    assert {item.cap for item in candidates} == set(StrokeCap)
    assert {item.join for item in candidates} == set(StrokeJoin)
