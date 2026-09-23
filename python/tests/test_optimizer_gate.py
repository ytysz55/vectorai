from __future__ import annotations

from dataclasses import replace

from vectorai_bench.optimizer_gate import (
    OptimizerCaseMeasurement,
    evaluate_optimizer_g4,
    optimizer_semantic_digest,
)


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
        "optimizer_stage_ms": {
            "scene_selection": 20.0,
            "export_editability": 10.0,
            "objective": 1.0,
            "render_rank": 150.0,
            "total": 181.0,
        },
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


def test_semantic_digest_excludes_all_runtime_observations() -> None:
    fast = [measurement("a"), measurement("b"), measurement("c")]
    slow = [
        replace(
            item,
            baseline_runtime_ms=item.baseline_runtime_ms * 101.0,
            optimized_runtime_ms=item.optimized_runtime_ms * 101.0,
            optimizer_stage_ms={
                key: value * 101.0 for key, value in item.optimizer_stage_ms.items()
            },
        )
        for item in fast
    ]

    fast_evaluation = evaluate_optimizer_g4(fast)
    slow_evaluation = evaluate_optimizer_g4(slow)

    assert fast_evaluation.passed
    assert not slow_evaluation.passed
    assert optimizer_semantic_digest(
        fast, fast_evaluation, "a" * 64, "b" * 64
    ) == optimizer_semantic_digest(
        slow,
        slow_evaluation,
        "a" * 64,
        "b" * 64,
    )


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
