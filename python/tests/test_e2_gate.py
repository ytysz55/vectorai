from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from vectorai_bench.e2_gate import E2Measurement, evaluate_g1, generate_e2_cases


def measurements(case_count: int, *, topology_failure: bool = False) -> list[E2Measurement]:
    result: list[E2Measurement] = []
    for index in range(case_count):
        case_id = f"case-{index}"
        exact = not topology_failure or index != 0
        result.extend(
            (
                E2Measurement(case_id, "engine-auto", "success", exact, 0.01, 4, 5.0),
                E2Measurement(case_id, "engine-no-subpixel", "success", exact, 0.02, 4, 4.0),
                E2Measurement(case_id, "engine-bezier-only", "success", exact, 0.012, 8, 6.0),
                E2Measurement(case_id, "vtracer", "success", True, 0.015, 6, 3.0),
                E2Measurement(case_id, "potrace", "success", True, 0.02, 10, 2.0),
            )
        )
    return result


def test_gate_passes_with_topology_and_node_advantage() -> None:
    result = evaluate_g1(measurements(20), case_count=20)
    assert result.passed
    assert result.exact_topology_rate == 1.0
    assert result.hard_failure_count == 0
    assert result.baseline_node_advantage["vtracer"] == 1.0 - 4.0 / 6.0
    assert result.baseline_node_advantage["potrace"] == 0.6
    assert result.no_subpixel_rmse_delta == pytest.approx(0.01)
    assert result.bezier_only_node_delta == 4.0


def test_gate_fails_below_exact_topology_threshold() -> None:
    result = evaluate_g1(measurements(20, topology_failure=True), case_count=20)
    assert result.exact_topology_rate == 0.95
    assert result.passed

    two_failures = measurements(20, topology_failure=True)
    for index, item in enumerate(two_failures):
        if item.case_id == "case-1" and item.runner == "engine-auto":
            two_failures[index] = E2Measurement(
                item.case_id, item.runner, item.status, False, 0.01, 4, 5.0
            )
    failed = evaluate_g1(two_failures, case_count=20)
    assert failed.exact_topology_rate == 0.9
    assert not failed.passed
    assert not failed.criteria["exact_topology_at_least_95_percent"]


def test_procedural_e2_corpus_covers_binary_topologies(tmp_path: Path) -> None:
    cases = generate_e2_cases(tmp_path, count=8)
    assert len(cases) == 8
    assert {case.topology.components for case in cases} == {1, 2}
    assert {case.topology.holes for case in cases} == {0, 1}
    for case in cases:
        with Image.open(case.source_path) as image:
            assert image.size == (128, 128)
            assert image.mode == "RGBA"
        assert case.reference_path.is_file()
