"""Solver-independent E5 parameter blocks and deterministic bounded refinement."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, replace
from enum import StrEnum

from .objectives import ObjectiveEvaluation
from .profiles import OptimizationLimits


class ParameterKind(StrEnum):
    VERTEX = "vertex"
    PRIMITIVE = "primitive"
    COLOR = "color"
    WIDTH = "width"


class OptimizationStatus(StrEnum):
    CONVERGED = "converged"
    ITERATION_LIMIT = "iteration_limit"
    EVALUATION_LIMIT = "evaluation_limit"
    DIVERGED = "diverged"
    BASELINE_INVALID = "baseline_invalid"


@dataclass(frozen=True, slots=True)
class ParameterBlock:
    stable_id: str
    kind: ParameterKind
    initial: tuple[float, ...]
    lower: tuple[float, ...]
    upper: tuple[float, ...]

    def __post_init__(self) -> None:
        if not self.stable_id:
            raise ValueError("parameter block stable ID must be nonempty")
        if not self.initial or not (len(self.initial) == len(self.lower) == len(self.upper)):
            raise ValueError("parameter block vectors must have equal nonzero length")
        for initial, lower, upper in zip(self.initial, self.lower, self.upper, strict=True):
            if not all(math.isfinite(value) for value in (initial, lower, upper)):
                raise ValueError("parameter block values and bounds must be finite")
            if lower > initial or initial > upper:
                raise ValueError("initial parameter must lie inside its bounds")


@dataclass(frozen=True, slots=True)
class SceneParameters:
    blocks: tuple[ParameterBlock, ...]
    values: tuple[tuple[float, ...], ...]

    def __post_init__(self) -> None:
        if len(self.blocks) != len(self.values):
            raise ValueError("parameter blocks and values must have equal length")
        identities = tuple((block.kind.value, block.stable_id) for block in self.blocks)
        if identities != tuple(sorted(identities)) or len(set(identities)) != len(identities):
            raise ValueError("parameter blocks must have unique canonical ordering")
        for block, values in zip(self.blocks, self.values, strict=True):
            if len(values) != len(block.initial):
                raise ValueError("parameter value vector has an invalid length")
            for value, lower, upper in zip(values, block.lower, block.upper, strict=True):
                if not math.isfinite(value) or not lower <= value <= upper:
                    raise ValueError("parameter value is non-finite or outside its bounds")

    @classmethod
    def baseline(cls, blocks: tuple[ParameterBlock, ...]) -> SceneParameters:
        ordered = tuple(sorted(blocks, key=lambda item: (item.kind.value, item.stable_id)))
        return cls(ordered, tuple(block.initial for block in ordered))

    def replace_component(
        self,
        block_index: int,
        component_index: int,
        value: float,
    ) -> SceneParameters:
        block_values = list(self.values[block_index])
        block_values[component_index] = value
        values = list(self.values)
        values[block_index] = tuple(block_values)
        return replace(self, values=tuple(values))


@dataclass(frozen=True, slots=True)
class AcceptedSnapshot:
    candidate_id: str
    evaluation_index: int
    score: float
    parameters: SceneParameters


@dataclass(frozen=True, slots=True)
class OptimizationResult:
    status: OptimizationStatus
    baseline: SceneParameters
    selected: SceneParameters
    baseline_evaluation: ObjectiveEvaluation | None
    selected_evaluation: ObjectiveEvaluation | None
    iterations: int
    evaluations: int
    accepted_snapshots: tuple[AcceptedSnapshot, ...]
    fallback_used: bool
    reason: str


Evaluator = Callable[[SceneParameters], ObjectiveEvaluation]


def _bounded_block(
    stable_id: str,
    kind: ParameterKind,
    initial: tuple[float, ...],
    deltas: tuple[float, ...],
    *,
    clamp_to_unit: bool = False,
    positive_indices: tuple[int, ...] = (),
    minimum_positive: float = 1.0e-6,
) -> ParameterBlock:
    if len(initial) != len(deltas) or any(delta < 0.0 for delta in deltas):
        raise ValueError("parameter deltas must be nonnegative and match initial values")
    positive = set(positive_indices)
    if any(index < 0 or index >= len(initial) for index in positive):
        raise ValueError("positive parameter index is out of range")
    lower: list[float] = []
    upper: list[float] = []
    for index, (value, delta) in enumerate(zip(initial, deltas, strict=True)):
        minimum = 0.0 if clamp_to_unit else value - delta
        maximum = 1.0 if clamp_to_unit else value + delta
        if index in positive:
            minimum = max(minimum, minimum_positive)
        lower.append(max(minimum, value - delta))
        upper.append(min(maximum, value + delta))
    return ParameterBlock(stable_id, kind, initial, tuple(lower), tuple(upper))


def vertex_parameter_block(
    stable_id: str,
    position: tuple[float, float],
    limits: OptimizationLimits,
) -> ParameterBlock:
    delta = limits.max_vertex_delta_px
    return _bounded_block(stable_id, ParameterKind.VERTEX, position, (delta, delta))


def primitive_parameter_block(
    stable_id: str,
    values: tuple[float, ...],
    positive_indices: tuple[int, ...],
    limits: OptimizationLimits,
) -> ParameterBlock:
    delta = limits.max_primitive_delta_px
    return _bounded_block(
        stable_id,
        ParameterKind.PRIMITIVE,
        values,
        tuple(delta for _ in values),
        positive_indices=positive_indices,
        minimum_positive=limits.minimum_positive_geometry,
    )


def color_parameter_block(
    stable_id: str,
    rgba: tuple[float, float, float, float],
    limits: OptimizationLimits,
) -> ParameterBlock:
    delta = limits.max_color_delta
    return _bounded_block(
        stable_id,
        ParameterKind.COLOR,
        rgba,
        (delta, delta, delta, delta),
        clamp_to_unit=True,
    )


def width_parameter_block(
    stable_id: str,
    widths: tuple[float, ...],
    limits: OptimizationLimits,
) -> ParameterBlock:
    delta = limits.max_width_delta_px
    return _bounded_block(
        stable_id,
        ParameterKind.WIDTH,
        widths,
        tuple(delta for _ in widths),
        positive_indices=tuple(range(len(widths))),
        minimum_positive=limits.minimum_positive_geometry,
    )


def optimize_parameters(
    blocks: tuple[ParameterBlock, ...],
    limits: OptimizationLimits,
    evaluator: Evaluator,
) -> OptimizationResult:
    """Run fixed-order projected coordinate descent without renderer calls."""

    baseline = SceneParameters.baseline(blocks)
    try:
        baseline_evaluation = evaluator(baseline)
    except Exception as error:
        return OptimizationResult(
            OptimizationStatus.BASELINE_INVALID,
            baseline,
            baseline,
            None,
            None,
            0,
            0,
            (),
            False,
            f"baseline evaluator failed: {type(error).__name__}",
        )
    if (
        not baseline_evaluation.hard_constraints_valid
        or baseline_evaluation.weighted_score is None
        or not math.isfinite(baseline_evaluation.weighted_score)
    ):
        return OptimizationResult(
            OptimizationStatus.BASELINE_INVALID,
            baseline,
            baseline,
            baseline_evaluation,
            baseline_evaluation,
            0,
            1,
            (),
            False,
            "pre-optimization scene failed hard validation",
        )

    selected = baseline
    selected_evaluation = baseline_evaluation
    evaluations = 1
    iterations = 0
    accepted: list[AcceptedSnapshot] = []
    stale_sweeps = 0
    status = OptimizationStatus.CONVERGED
    reason = "step schedule exhausted"

    try:
        limit_reached = False
        for step in limits.step_schedule:
            if stale_sweeps >= limits.early_stop_patience:
                reason = "early stop patience reached"
                break
            if iterations >= limits.max_iterations:
                status = OptimizationStatus.ITERATION_LIMIT
                reason = "maximum iterations reached"
                break
            improved_in_sweep = False
            for block_index, block in enumerate(selected.blocks):
                for component_index in range(len(block.initial)):
                    for direction in (-1.0, 1.0):
                        if evaluations >= limits.max_evaluations:
                            status = OptimizationStatus.EVALUATION_LIMIT
                            reason = "maximum evaluations reached"
                            limit_reached = True
                            break
                        current = selected.values[block_index][component_index]
                        proposed = min(
                            block.upper[component_index],
                            max(block.lower[component_index], current + direction * step),
                        )
                        if proposed == current:
                            continue
                        candidate = selected.replace_component(
                            block_index, component_index, proposed
                        )
                        evaluation = evaluator(candidate)
                        evaluations += 1
                        score = evaluation.weighted_score
                        if (
                            not evaluation.hard_constraints_valid
                            or score is None
                            or not math.isfinite(score)
                        ):
                            continue
                        selected_score = selected_evaluation.weighted_score
                        if selected_score is None:
                            raise ArithmeticError("selected candidate lost its score")
                        if score <= selected_score - limits.minimum_improvement:
                            selected = candidate
                            selected_evaluation = evaluation
                            improved_in_sweep = True
                            accepted.append(
                                AcceptedSnapshot(
                                    candidate_id=f"candidate-{len(accepted) + 1:06d}",
                                    evaluation_index=evaluations,
                                    score=score,
                                    parameters=candidate,
                                )
                            )
                    if limit_reached:
                        break
                if limit_reached:
                    break
            if limit_reached:
                break
            iterations += 1
            stale_sweeps = 0 if improved_in_sweep else stale_sweeps + 1
    except Exception as error:
        return OptimizationResult(
            OptimizationStatus.DIVERGED,
            baseline,
            baseline,
            baseline_evaluation,
            baseline_evaluation,
            iterations,
            evaluations,
            tuple(accepted),
            True,
            f"optimizer diverged: {type(error).__name__}",
        )

    return OptimizationResult(
        status,
        baseline,
        selected,
        baseline_evaluation,
        selected_evaluation,
        iterations,
        evaluations,
        tuple(accepted),
        False,
        reason,
    )
