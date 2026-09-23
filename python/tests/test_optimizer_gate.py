from __future__ import annotations

from dataclasses import replace

from vectorai_bench.optimizer_gate import OptimizerCaseMeasurement, evaluate_optimizer_g4


def measurement(case_id: str, **changes: object) -> OptimizerCaseMeasurement:
    values: dict[str, object] = {
        "case_id": case_id,
        "exact_topology": True,
        "fallback_used": False,
        "baseline_node_count": 100,
        "optimized_node_count": 75,
        "baseline_rmse": 0.10,
        "optimized_rmse": 0.08,
        "fidelity_improvement": 0.02,
        "node_advantage": 0.25,
        "baseline_runtime_ms": 100.0,
        "optimized_runtime_ms": 200.0,
    }
    values.update(changes)
    return OptimizerCaseMeasurement(**values)  # type: ignore[arg-type]


def test_g4_requires_topology_nodes_fidelity_and_runtime() -> None:
    evaluation = evaluate_optimizer_g4(
        [
            measurement("a"),
            measurement("b", fidelity_improvement=0.01),
            measurement("c", fidelity_improvement=0.03),
        ]
    )

    assert evaluation.passed
    assert evaluation.exact_topology_rate == 1.0
    assert evaluation.median_fidelity_improvement == 0.02
    assert evaluation.mean_fidelity_improvement == 0.02
    assert evaluation.improved_case_count == 3
    assert evaluation.fidelity_regression_count == 0
    assert evaluation.median_node_advantage == 0.25
    assert all(evaluation.criteria.values())


def test_g4_rejects_each_hard_regression() -> None:
    baseline = measurement("a")
    cases = (
        (replace(baseline, exact_topology=False), "exact_topology"),
        (replace(baseline, fallback_used=True), "zero_fallback"),
        (
            replace(baseline, optimized_node_count=101, node_advantage=-0.01),
            "zero_node_regression",
        ),
        (replace(baseline, fidelity_improvement=-0.001), "zero_fidelity_regression"),
        (replace(baseline, optimized_runtime_ms=20_001.0), "runtime_p95_within_20s"),
    )

    for case, failed_criterion in cases:
        evaluation = evaluate_optimizer_g4([case, measurement("b"), measurement("c")])
        assert not evaluation.passed
        assert not evaluation.criteria[failed_criterion]
