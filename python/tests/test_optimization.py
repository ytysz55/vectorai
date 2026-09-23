from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from vectorai_engine.objectives import ObjectiveContext, RawObjectiveTerms, evaluate_objective
from vectorai_engine.optimization import (
    OptimizationStatus,
    SceneParameters,
    color_parameter_block,
    optimize_parameters,
    primitive_parameter_block,
    vertex_parameter_block,
    width_parameter_block,
)
from vectorai_engine.optimization_validation import (
    TopologySignature,
    compare_topology_signatures,
)
from vectorai_engine.profiles import OptimizationLimits, load_optimizer_profiles

ROOT = Path(__file__).resolve().parents[2]
PROFILE_PATH = ROOT / "benchmark" / "configs" / "optimizer-profiles-v1.json"


def limits() -> OptimizationLimits:
    return load_optimizer_profiles(PROFILE_PATH).select("geometric").limits


def signature(**changes: object) -> TopologySignature:
    values: dict[str, object] = {
        "components": 1,
        "holes": 0,
        "adjacency": ((1, 2),),
        "face_cycles": ((1, 2, 3), (4, 5, 6)),
        "canonical_edge_owners": ((1, 1, 2),),
        "shared_geometry_keys": ("edge-1",),
        "closed_cycles": (True, True),
        "stroke_edges": (),
        "junction_valence": (),
        "path_count": 2,
        "node_count": 6,
    }
    values.update(changes)
    return TopologySignature(**values)  # type: ignore[arg-type]


def test_parameter_blocks_apply_vertex_primitive_color_and_width_bounds() -> None:
    profile_limits = limits()
    vertex = vertex_parameter_block("vertex-1", (10.0, 20.0), profile_limits)
    primitive = primitive_parameter_block(
        "primitive-1",
        (5.0, 6.0, 2.0),
        (2,),
        profile_limits,
    )
    color = color_parameter_block("color-1", (0.02, 0.5, 0.98, 1.0), profile_limits)
    width = width_parameter_block("width-1", (0.2, 4.0), profile_limits)

    assert vertex.lower == (8.0, 18.0)
    assert vertex.upper == (12.0, 22.0)
    assert primitive.lower[2] == profile_limits.minimum_positive_geometry
    assert primitive.upper[2] == 4.0
    assert color.lower == (0.0, 0.42, 0.9, 0.92)
    assert color.upper == (0.1, 0.58, 1.0, 1.0)
    assert width.lower[0] == profile_limits.minimum_positive_geometry
    assert width.upper == (1.7, 5.5)


def test_topology_signature_changes_are_hard_violations() -> None:
    baseline = signature()
    same = compare_topology_signatures(baseline, signature())
    changed = compare_topology_signatures(
        baseline,
        signature(adjacency=((1, 3),), node_count=7),
    )

    assert same.valid
    assert same.violations == ()
    assert not changed.valid
    assert changed.violations == ("adjacency_changed", "node_count_changed")


@pytest.mark.parametrize(
    ("field_name", "changed_value"),
    [
        ("components", 2),
        ("holes", 1),
        ("adjacency", ((1, 3),)),
        ("face_cycles", ((1, 3, 2), (4, 5, 6))),
        ("canonical_edge_owners", ((1, 1, 3),)),
        ("shared_geometry_keys", ("edge-2",)),
        ("closed_cycles", (True, False)),
        ("stroke_edges", ((1, 2),)),
        ("junction_valence", ((1, 3),)),
        ("path_count", 3),
        ("node_count", 7),
    ],
)
def test_every_topology_field_is_noncompensable(
    field_name: str,
    changed_value: Any,
) -> None:
    baseline = signature()
    candidate = replace(baseline, **{field_name: changed_value})

    validation = compare_topology_signatures(baseline, candidate)

    assert validation.violations == (f"{field_name}_changed",)


def test_projected_optimizer_is_deterministic_and_bounded() -> None:
    profile = load_optimizer_profiles(PROFILE_PATH).select("geometric")
    block = vertex_parameter_block("vertex-1", (0.0, 0.0), profile.limits)
    context = ObjectiveContext(10, 10, 2)

    def evaluator(parameters: SceneParameters):  # type: ignore[no-untyped-def]
        x, y = parameters.values[0]
        return evaluate_objective(
            RawObjectiveTerms(abs(x - 1.0) / 10.0 + abs(y + 0.5) / 10.0, 0.0, 2, 0.0, 0.0),
            context,
            profile.weights.as_mapping(),
        )

    first = optimize_parameters((block,), profile.limits, evaluator)
    second = optimize_parameters((block,), profile.limits, evaluator)

    assert first == second
    assert first.status is OptimizationStatus.CONVERGED
    assert first.selected.values[0] == (1.0, -0.5)
    assert 1 < first.evaluations <= profile.limits.max_evaluations
    assert first.iterations <= profile.limits.max_iterations
    assert first.accepted_snapshots


def test_optimizer_rejects_hard_invalid_proposals() -> None:
    profile = load_optimizer_profiles(PROFILE_PATH).select("geometric")
    block = vertex_parameter_block("vertex-1", (0.0, 0.0), profile.limits)
    context = ObjectiveContext(10, 10, 2)

    def evaluator(parameters: SceneParameters):  # type: ignore[no-untyped-def]
        x = parameters.values[0][0]
        violations = ("adjacency_changed",) if x != 0.0 else ()
        return evaluate_objective(
            RawObjectiveTerms(abs(x - 1.0) / 10.0, 0.0, 2, 0.0, 0.0),
            context,
            profile.weights.as_mapping(),
            hard_constraint_violations=violations,
        )

    result = optimize_parameters((block,), profile.limits, evaluator)

    assert result.selected == result.baseline
    assert not result.fallback_used


def test_divergence_uses_only_the_validated_baseline() -> None:
    profile = load_optimizer_profiles(PROFILE_PATH).select("geometric")
    constrained_limits = replace(profile.limits, step_schedule=(1.0,))
    block = vertex_parameter_block("vertex-1", (0.0, 0.0), constrained_limits)
    context = ObjectiveContext(10, 10, 2)
    calls = 0

    def evaluator(parameters: SceneParameters):  # type: ignore[no-untyped-def]
        nonlocal calls
        calls += 1
        if calls > 1:
            raise ArithmeticError("synthetic divergence")
        return evaluate_objective(
            RawObjectiveTerms(0.2, 0.0, 2, 0.0, 0.0),
            context,
            profile.weights.as_mapping(),
        )

    result = optimize_parameters((block,), constrained_limits, evaluator)

    assert result.status is OptimizationStatus.DIVERGED
    assert result.fallback_used
    assert result.selected == result.baseline
    assert result.selected_evaluation == result.baseline_evaluation


def test_invalid_baseline_is_never_used_as_fallback() -> None:
    profile = load_optimizer_profiles(PROFILE_PATH).select("geometric")
    block = vertex_parameter_block("vertex-1", (0.0, 0.0), profile.limits)

    def evaluator(parameters: SceneParameters):  # type: ignore[no-untyped-def]
        del parameters
        return evaluate_objective(
            RawObjectiveTerms(0.0, 0.0, 2, 0.0, 0.0),
            ObjectiveContext(10, 10, 2),
            profile.weights.as_mapping(),
            hard_constraint_violations=("cycle_open",),
        )

    result = optimize_parameters((block,), profile.limits, evaluator)

    assert result.status is OptimizationStatus.BASELINE_INVALID
    assert not result.fallback_used
