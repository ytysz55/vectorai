from __future__ import annotations

import numpy as np

from vectorai_engine.stroke_routing import RouteKind, classify_fill_stroke


def test_routes_compact_fills_and_thin_lines() -> None:
    fill = np.zeros((64, 64), dtype=np.bool_)
    fill[16:48, 16:48] = True
    line = np.zeros((64, 96), dtype=np.bool_)
    line[29:36, 8:88] = True

    assert classify_fill_stroke(fill).selected is RouteKind.FILL
    decision = classify_fill_stroke(line)
    assert decision.selected is RouteKind.STROKE
    assert "THIN_REGION" in decision.reasons


def test_closed_ring_uses_low_confidence_fill_fallback() -> None:
    y, x = np.ogrid[:80, :80]
    outer = (x - 40) ** 2 + (y - 40) ** 2 <= 28**2
    inner = (x - 40) ** 2 + (y - 40) ** 2 < 20**2
    decision = classify_fill_stroke(outer & ~inner)

    assert decision.selected is RouteKind.AMBIGUOUS
    assert decision.fallback is RouteKind.FILL
    assert decision.confidence == 0.0
    assert "CLOSED_RING_AMBIGUITY" in decision.reasons
