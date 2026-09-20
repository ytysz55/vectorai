from __future__ import annotations

import math

import pytest

from vectorai_bench.metrics import (
    Junction,
    compare_boundaries,
    compare_corners,
    compare_junctions,
)

SQUARE = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]


def test_identical_boundaries_have_zero_distance() -> None:
    metrics = compare_boundaries(SQUARE, SQUARE, image_width=10, image_height=10)
    assert metrics.chamfer == pytest.approx(0.0)
    assert metrics.hausdorff == pytest.approx(0.0)


def test_shifted_boundaries_have_known_normalized_distance() -> None:
    shifted = [(x + 3.0, y + 4.0) for x, y in SQUARE]
    metrics = compare_boundaries(SQUARE, shifted, image_width=10, image_height=10)
    expected = 5.0 / math.hypot(10, 10)
    assert metrics.chamfer == pytest.approx(expected)
    assert metrics.hausdorff == pytest.approx(expected)


def test_corner_matching_reports_precision_recall_and_localization() -> None:
    predicted = [(0.5, 0.0), (10.0, 0.5), (50.0, 50.0)]
    metrics = compare_corners(
        SQUARE,
        predicted,
        tolerance_px=1.0,
        image_width=100,
        image_height=100,
    )
    assert metrics.matched == 2
    assert metrics.precision == pytest.approx(2 / 3)
    assert metrics.recall == pytest.approx(0.5)
    assert metrics.f1 == pytest.approx(4 / 7)
    assert metrics.mean_localization_error == pytest.approx(0.5 / math.hypot(100, 100))


def test_junction_matching_requires_correct_degree() -> None:
    reference = (Junction(10.0, 10.0, 3), Junction(30.0, 30.0, 4))
    predicted = (Junction(10.1, 10.1, 4), Junction(30.2, 30.0, 4))
    metrics = compare_junctions(
        reference,
        predicted,
        tolerance_px=1.0,
        image_width=100,
        image_height=100,
    )
    assert metrics.matched == 1
    assert metrics.precision == metrics.recall == metrics.f1 == 0.5


def test_empty_boundary_is_rejected() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        compare_boundaries([], SQUARE, image_width=10, image_height=10)
