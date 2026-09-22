from __future__ import annotations

import numpy as np

from vectorai_engine.errors import RunStatus
from vectorai_engine.stroke_routing import RouteKind, classify_fill_stroke
from vectorai_engine.stroke_selection import (
    HypothesisKind,
    StrokeCandidateEvaluation,
    arbitrate_fill_stroke,
)


def routing(stroke: bool = True):  # type: ignore[no-untyped-def]
    mask = np.zeros((48, 96), dtype=np.bool_)
    if stroke:
        mask[20:27, 8:88] = True
    else:
        mask[8:40, 24:72] = True
    return classify_fill_stroke(mask)


def test_same_fidelity_band_prefers_lower_node_stroke() -> None:
    candidates = (
        StrokeCandidateEvaluation("fill", HypothesisKind.FILL, True, 0.0, 12, 0.006),
        StrokeCandidateEvaluation("stroke", HypothesisKind.STROKE, True, 0.018, 2, 0.019),
    )
    result = arbitrate_fill_stroke(candidates, routing())
    assert result.selected.kind is HypothesisKind.STROKE
    assert result.status is RunStatus.SUCCESS


def test_ambiguous_routing_requires_review() -> None:
    y, x = np.ogrid[:64, :64]
    ring = ((x - 32) ** 2 + (y - 32) ** 2 <= 24**2) & ((x - 32) ** 2 + (y - 32) ** 2 >= 16**2)
    decision = classify_fill_stroke(ring)
    assert decision.selected is RouteKind.AMBIGUOUS
    candidates = (
        StrokeCandidateEvaluation("fill", HypothesisKind.FILL, True, 0.01, 10, 0.015),
        StrokeCandidateEvaluation("stroke", HypothesisKind.STROKE, True, 0.01, 4, 0.012),
    )
    result = arbitrate_fill_stroke(candidates, decision)
    assert result.status is RunStatus.NEEDS_REVIEW
