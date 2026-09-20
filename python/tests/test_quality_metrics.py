from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pytest

from vectorai_bench.metrics.editability import measure_svg_editability
from vectorai_bench.metrics.fidelity import compare_rgba, srgb_to_linear
from vectorai_bench.metrics.resources import measure_callable


def test_identical_rgba_has_zero_error() -> None:
    image = np.array([[[10, 20, 30, 255], [200, 100, 50, 128]]], dtype=np.uint8)
    metrics = compare_rgba(image, image)
    assert metrics.linear_rgb_mae == 0.0
    assert metrics.alpha_mae == 0.0
    assert metrics.premultiplied_rgba_rmse == 0.0
    assert metrics.max_channel_error == 0.0


def test_transparent_rgb_is_ignored_by_premultiplication() -> None:
    reference = np.array([[[0, 0, 0, 0]]], dtype=np.uint8)
    predicted = np.array([[[255, 100, 50, 0]]], dtype=np.uint8)
    metrics = compare_rgba(reference, predicted)
    assert metrics.linear_rgb_mae == 0.0
    assert metrics.premultiplied_rgba_rmse == 0.0


def test_alpha_error_is_measured_independently() -> None:
    reference = np.array([[[255, 0, 0, 255]]], dtype=np.uint8)
    predicted = np.array([[[255, 0, 0, 0]]], dtype=np.uint8)
    metrics = compare_rgba(reference, predicted)
    assert metrics.alpha_mae == 1.0
    assert metrics.linear_rgb_mae == pytest.approx(1 / 3)
    assert metrics.max_channel_error == 1.0


def test_srgb_transfer_function_calibration() -> None:
    values = np.array([0.0, 0.04045, 1.0], dtype=np.float64)
    linear = srgb_to_linear(values)
    assert float(linear[0]) == 0.0
    assert float(linear[1]) == pytest.approx(0.04045 / 12.92)
    assert float(linear[2]) == 1.0


def test_shape_mismatch_is_rejected() -> None:
    with pytest.raises(ValueError, match="shapes must match"):
        compare_rgba(
            np.zeros((2, 2, 4), dtype=np.uint8),
            np.zeros((3, 2, 4), dtype=np.uint8),
        )


def test_svg_complexity_counts_paths_primitives_segments_and_nodes(tmp_path: Path) -> None:
    svg = tmp_path / "fixture.svg"
    svg.write_text(
        """<svg xmlns="http://www.w3.org/2000/svg">
<g><path d="M0 0 L10 0 10 10 Z"/><rect x="0" y="0" width="2" height="2"/>
<circle cx="4" cy="4" r="1"/><polyline points="0,0 1,1 2,1"/></g></svg>""",
        encoding="utf-8",
    )
    metrics = measure_svg_editability(svg)
    assert metrics.path_count == 1
    assert metrics.primitive_count == 3
    assert metrics.group_count == 1
    assert metrics.node_count == 3 + 4 + 4 + 3
    assert metrics.segment_count == 3 + 4 + 4 + 2
    assert metrics.unsupported_element_count == 0


def test_unsupported_elements_are_visible(tmp_path: Path) -> None:
    svg = tmp_path / "text.svg"
    svg.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg"><text>editable text</text></svg>',
        encoding="utf-8",
    )
    assert measure_svg_editability(svg).unsupported_element_count == 1


def test_resource_measurement_returns_value_and_observations() -> None:
    def operation() -> int:
        payload = bytearray(2_000_000)
        time.sleep(0.01)
        return len(payload)

    measured = measure_callable(operation)
    assert measured.value == 2_000_000
    assert measured.resources.wall_time_ms >= 5.0
    assert measured.resources.cpu_time_ms >= 0.0
    assert measured.resources.peak_rss_bytes > 0
