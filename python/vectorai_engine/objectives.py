"""Normalized, topology-gated objective terms for E5 optimization."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass

OBJECTIVE_NORMALIZATION_VERSION = "1.0.0"
TERM_NAMES = ("fidelity", "boundary", "complexity", "regularization", "color")


@dataclass(frozen=True, slots=True)
class ObjectiveContext:
    width: int
    height: int
    baseline_node_count: int

    def __post_init__(self) -> None:
        if self.width < 1 or self.height < 1 or self.baseline_node_count < 1:
            raise ValueError("objective context dimensions and baseline nodes must be positive")

    @property
    def image_diagonal(self) -> float:
        return math.hypot(self.width, self.height)


@dataclass(frozen=True, slots=True)
class RawObjectiveTerms:
    premultiplied_rgba_rmse: float
    boundary_rms_px: float
    node_count: int
    regularization_rms_px: float
    color_rms: float

    def __post_init__(self) -> None:
        finite_values = (
            self.premultiplied_rgba_rmse,
            self.boundary_rms_px,
            self.regularization_rms_px,
            self.color_rms,
        )
        if not all(math.isfinite(value) for value in finite_values):
            raise ValueError("objective terms must be finite")
        if not 0.0 <= self.premultiplied_rgba_rmse <= 1.0:
            raise ValueError("premultiplied RGBA RMSE must be in [0, 1]")
        if self.boundary_rms_px < 0.0 or self.regularization_rms_px < 0.0:
            raise ValueError("pixel residuals must be nonnegative")
        if self.node_count < 0:
            raise ValueError("node count must be nonnegative")
        if not 0.0 <= self.color_rms <= 1.0:
            raise ValueError("color RMS must be in [0, 1]")


@dataclass(frozen=True, slots=True)
class NormalizedObjectiveTerms:
    fidelity: float
    boundary: float
    complexity: float
    regularization: float
    color: float

    def __post_init__(self) -> None:
        if not all(
            math.isfinite(value) and 0.0 <= value <= 1.0
            for value in (
                self.fidelity,
                self.boundary,
                self.complexity,
                self.regularization,
                self.color,
            )
        ):
            raise ValueError("normalized objective terms must be finite values in [0, 1]")

    def as_mapping(self) -> dict[str, float]:
        return {
            "fidelity": self.fidelity,
            "boundary": self.boundary,
            "complexity": self.complexity,
            "regularization": self.regularization,
            "color": self.color,
        }


@dataclass(frozen=True, slots=True)
class ObjectiveEvaluation:
    normalization_version: str
    hard_constraints_valid: bool
    terms: NormalizedObjectiveTerms
    weighted_score: float | None
    violations: tuple[str, ...]


def _unit_interval(value: float) -> float:
    return min(1.0, max(0.0, value))


def normalize_objective_terms(
    raw: RawObjectiveTerms,
    context: ObjectiveContext,
) -> NormalizedObjectiveTerms:
    """Normalize mixed-unit terms while preserving image-scale equivalence."""

    diagonal = context.image_diagonal
    complexity_ratio = raw.node_count / context.baseline_node_count
    return NormalizedObjectiveTerms(
        fidelity=raw.premultiplied_rgba_rmse,
        boundary=_unit_interval(raw.boundary_rms_px / diagonal),
        complexity=complexity_ratio / (1.0 + complexity_ratio),
        regularization=_unit_interval(raw.regularization_rms_px / diagonal),
        color=raw.color_rms,
    )


def evaluate_objective(
    raw: RawObjectiveTerms,
    context: ObjectiveContext,
    weights: Mapping[str, float],
    *,
    hard_constraint_violations: tuple[str, ...] = (),
) -> ObjectiveEvaluation:
    """Return a weighted score only for a hard-valid candidate."""

    if set(weights) != set(TERM_NAMES):
        raise ValueError(f"objective weights must contain exactly {TERM_NAMES}")
    weight_values = tuple(weights[name] for name in TERM_NAMES)
    if not all(math.isfinite(value) and value >= 0.0 for value in weight_values):
        raise ValueError("objective weights must be finite and nonnegative")
    if not math.isclose(sum(weight_values), 1.0, rel_tol=0.0, abs_tol=1.0e-12):
        raise ValueError("objective weights must sum to one")
    if any(not violation for violation in hard_constraint_violations):
        raise ValueError("hard constraint violation identifiers must be nonempty")

    terms = normalize_objective_terms(raw, context)
    valid = not hard_constraint_violations
    weighted_score = (
        sum(weights[name] * terms.as_mapping()[name] for name in TERM_NAMES) if valid else None
    )
    return ObjectiveEvaluation(
        normalization_version=OBJECTIVE_NORMALIZATION_VERSION,
        hard_constraints_valid=valid,
        terms=terms,
        weighted_score=weighted_score,
        violations=hard_constraint_violations,
    )
