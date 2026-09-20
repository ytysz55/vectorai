from __future__ import annotations

from pathlib import Path

from PIL import Image

from vectorai_bench.multicolor_gate import (
    MulticolorMeasurement,
    evaluate_multicolor_g2,
    generate_multicolor_cases,
)


def measurements(case_count: int, *, seam_gap: float = 0.0) -> list[MulticolorMeasurement]:
    result: list[MulticolorMeasurement] = []
    for index in range(case_count):
        case_id = f"case-{index}"
        result.append(MulticolorMeasurement(case_id, "engine", "success", True, 0.01, 8, seam_gap))
        result.append(MulticolorMeasurement(case_id, "vtracer", "success", None, 0.02, 12, None))
    return result


def test_g2_evaluation_requires_topology_seams_and_fidelity_band() -> None:
    evaluation = evaluate_multicolor_g2(measurements(10), case_count=10)
    assert evaluation.passed
    assert evaluation.exact_topology_rate == 1.0
    assert evaluation.maximum_seam_gap_rate == 0.0
    assert evaluation.node_advantage_vs_vtracer == 1.0 - 8.0 / 12.0
    assert evaluation.fidelity_band_comparisons == 10


def test_g2_evaluation_fails_with_transparent_seam() -> None:
    evaluation = evaluate_multicolor_g2(measurements(10, seam_gap=0.1), case_count=10)
    assert not evaluation.passed
    assert not evaluation.criteria["renderer_seams_have_no_transparent_gap"]


def test_g2_evaluation_fails_with_negative_node_advantage() -> None:
    cases = measurements(10)
    for index, item in enumerate(cases):
        if item.runner == "engine":
            cases[index] = MulticolorMeasurement(
                item.case_id,
                item.runner,
                item.status,
                item.exact_topology,
                item.premultiplied_rgba_rmse,
                16,
                item.seam_gap_rate,
            )
    evaluation = evaluate_multicolor_g2(cases, case_count=10)
    assert not evaluation.passed
    assert evaluation.node_advantage_vs_vtracer is not None
    assert evaluation.node_advantage_vs_vtracer < 0.0
    assert not evaluation.criteria["vtracer_node_advantage_nonnegative"]


def test_multicolor_corpus_covers_two_through_twelve_colors(tmp_path: Path) -> None:
    cases = generate_multicolor_cases(tmp_path)
    assert [case.palette_count for case in cases] == list(range(2, 13))
    assert [case.region_count for case in cases] == list(range(2, 13))
    assert [case.adjacency_count for case in cases] == list(range(1, 12))
    for case in cases:
        with Image.open(case.source_path) as image:
            assert image.size == (case.palette_count * 12, 48)
