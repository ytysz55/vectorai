from __future__ import annotations

import math

import pytest

from vectorai_engine.objectives import (
    OBJECTIVE_NORMALIZATION_VERSION,
    ObjectiveContext,
    RawObjectiveTerms,
    evaluate_objective,
    normalize_objective_terms,
)

WEIGHTS = {
    "fidelity": 0.4,
    "boundary": 0.2,
    "complexity": 0.2,
    "regularization": 0.1,
    "color": 0.1,
}


def test_each_objective_term_has_explicit_unit_normalization() -> None:
    context = ObjectiveContext(width=3, height=4, baseline_node_count=20)
    terms = normalize_objective_terms(
        RawObjectiveTerms(
            premultiplied_rgba_rmse=0.25,
            boundary_rms_px=2.5,
            node_count=20,
            regularization_rms_px=1.25,
            color_rms=0.125,
        ),
        context,
    )

    assert terms.fidelity == 0.25
    assert terms.boundary == 0.5
    assert terms.complexity == 0.5
    assert terms.regularization == 0.25
    assert terms.color == 0.125


def test_pixel_terms_and_complexity_are_scale_invariant() -> None:
    small = normalize_objective_terms(
        RawObjectiveTerms(0.1, 0.5, 30, 0.25, 0.2),
        ObjectiveContext(width=3, height=4, baseline_node_count=60),
    )
    doubled = normalize_objective_terms(
        RawObjectiveTerms(0.1, 1.0, 60, 0.5, 0.2),
        ObjectiveContext(width=6, height=8, baseline_node_count=120),
    )

    assert doubled == small


def test_residuals_saturate_without_nonfinite_scores() -> None:
    terms = normalize_objective_terms(
        RawObjectiveTerms(1.0, 1.0e100, 10**100, 1.0e100, 1.0),
        ObjectiveContext(width=1, height=1, baseline_node_count=1),
    )

    assert terms.fidelity == 1.0
    assert terms.boundary == 1.0
    assert 0.0 < terms.complexity <= 1.0
    assert terms.regularization == 1.0
    assert terms.color == 1.0
    assert all(math.isfinite(value) for value in terms.as_mapping().values())


def test_hard_topology_failure_is_not_a_weighted_penalty() -> None:
    evaluation = evaluate_objective(
        RawObjectiveTerms(0.1, 0.2, 8, 0.3, 0.05),
        ObjectiveContext(width=16, height=12, baseline_node_count=10),
        WEIGHTS,
        hard_constraint_violations=("adjacency_changed",),
    )

    assert evaluation.normalization_version == OBJECTIVE_NORMALIZATION_VERSION
    assert not evaluation.hard_constraints_valid
    assert evaluation.weighted_score is None
    assert evaluation.violations == ("adjacency_changed",)


def test_valid_weighted_score_is_the_profile_dot_product() -> None:
    evaluation = evaluate_objective(
        RawObjectiveTerms(0.2, 5.0, 10, 2.5, 0.1),
        ObjectiveContext(width=6, height=8, baseline_node_count=10),
        WEIGHTS,
    )

    assert evaluation.hard_constraints_valid
    assert evaluation.weighted_score is not None
    assert abs(evaluation.weighted_score - 0.315) < 1.0e-12


@pytest.mark.parametrize(
    "raw",
    [
        RawObjectiveTerms(-0.0, 0.0, 0, 0.0, 0.0),
        RawObjectiveTerms(0.0, 0.0, 0, 0.0, 0.0),
    ],
)
def test_zero_terms_are_supported(raw: RawObjectiveTerms) -> None:
    terms = normalize_objective_terms(raw, ObjectiveContext(1, 1, 1))
    assert terms.as_mapping() == {
        "fidelity": 0.0,
        "boundary": 0.0,
        "complexity": 0.0,
        "regularization": 0.0,
        "color": 0.0,
    }


def test_invalid_units_and_weights_are_rejected() -> None:
    with pytest.raises(ValueError):
        RawObjectiveTerms(float("nan"), 0.0, 1, 0.0, 0.0)
    with pytest.raises(ValueError):
        ObjectiveContext(0, 10, 1)
    with pytest.raises(ValueError):
        evaluate_objective(
            RawObjectiveTerms(0.0, 0.0, 1, 0.0, 0.0),
            ObjectiveContext(10, 10, 1),
            {**WEIGHTS, "fidelity": 0.5},
        )
