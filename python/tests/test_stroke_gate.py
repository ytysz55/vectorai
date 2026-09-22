from __future__ import annotations

from dataclasses import replace

from vectorai_bench.stroke_gate import StrokeMeasurement, evaluate_stroke_g3


def passing_measurements() -> list[StrokeMeasurement]:
    return [
        StrokeMeasurement(
            case_id=f"stroke-{index}",
            status="success",
            route_expected="stroke",
            route_actual="stroke",
            route_correct=True,
            connectivity_exact=True,
            junction_exact=True,
            centerline_p95=0.5,
            width_error=0.25,
            width_model="constant",
            cap_exact=True,
            join_exact=True,
            stroke_rmse=0.02,
            fill_rmse=0.01,
            stroke_nodes=4,
            fill_nodes=12,
            selected_kind="stroke",
            cut_outline_valid=True,
        )
        for index in range(10)
    ]


def test_g3_requires_topology_geometry_fidelity_and_node_advantage() -> None:
    evaluation = evaluate_stroke_g3(passing_measurements())
    assert evaluation.passed
    assert evaluation.routing_accuracy == 1.0
    assert evaluation.connectivity_accuracy == 1.0
    assert evaluation.node_advantage_vs_fill == 1.0 - 4.0 / 12.0


def test_g3_fails_on_junction_or_node_regression() -> None:
    measurements = passing_measurements()
    first = measurements[0]
    measurements[0] = replace(first, junction_exact=False, stroke_nodes=20)
    evaluation = evaluate_stroke_g3(measurements)
    assert not evaluation.passed
    assert not evaluation.criteria["junction_valence_exact"]
