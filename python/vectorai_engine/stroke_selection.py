"""Topology-first arbitration between fill and stroke scene hypotheses."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .errors import RunStatus
from .stroke_models import StrokeStyle
from .stroke_routing import RouteKind, RoutingDecision


class HypothesisKind(StrEnum):
    FILL = "fill"
    STROKE = "stroke"


@dataclass(frozen=True, slots=True)
class StrokeCandidateEvaluation:
    candidate_id: str
    kind: HypothesisKind
    exact_topology: bool
    premultiplied_rgba_rmse: float
    node_count: int
    score: float
    style: StrokeStyle | None = None


@dataclass(frozen=True, slots=True)
class StrokeArbitration:
    selected: StrokeCandidateEvaluation
    ranked: tuple[StrokeCandidateEvaluation, ...]
    confidence: float
    status: RunStatus
    score_margin: float


def candidate_score(
    *,
    kind: HypothesisKind,
    exact_topology: bool,
    premultiplied_rgba_rmse: float,
    node_count: int,
    routing: RoutingDecision,
    complexity_weight: float = 5.0e-4,
    routing_weight: float = 0.01,
) -> float:
    if not 0.0 <= premultiplied_rgba_rmse <= 1.0 or node_count < 0:
        raise ValueError("candidate metrics are outside supported bounds")
    topology_penalty = 1_000.0 if not exact_topology else 0.0
    if kind is HypothesisKind.STROKE:
        routing_penalty = routing_weight * max(0.0, 0.5 - routing.stroke_score)
    else:
        routing_penalty = routing_weight * max(0.0, routing.stroke_score - 0.5)
    return (
        topology_penalty
        + premultiplied_rgba_rmse
        + complexity_weight * node_count
        + routing_penalty
    )


def arbitrate_fill_stroke(
    candidates: tuple[StrokeCandidateEvaluation, ...],
    routing: RoutingDecision,
    *,
    minimum_confident_margin: float = 0.005,
    fidelity_band: float = 0.02,
) -> StrokeArbitration:
    if not candidates:
        raise ValueError("at least one fill/stroke candidate is required")
    if minimum_confident_margin < 0.0 or fidelity_band < 0.0:
        raise ValueError("arbitration tolerances must be nonnegative")
    ranked = tuple(
        sorted(
            candidates,
            key=lambda item: (
                not item.exact_topology,
                item.score,
                item.node_count,
                item.kind.value,
                item.candidate_id,
            ),
        )
    )
    selected = ranked[0]
    best_fill = next((item for item in ranked if item.kind is HypothesisKind.FILL), None)
    best_stroke = next((item for item in ranked if item.kind is HypothesisKind.STROKE), None)
    if best_fill is not None and best_stroke is not None:
        if (
            best_fill.exact_topology
            and best_stroke.exact_topology
            and best_stroke.premultiplied_rgba_rmse
            <= best_fill.premultiplied_rgba_rmse + fidelity_band
            and best_stroke.node_count < best_fill.node_count
        ):
            selected = best_stroke
        elif (
            best_fill.exact_topology
            and best_stroke.exact_topology
            and best_fill.premultiplied_rgba_rmse
            <= best_stroke.premultiplied_rgba_rmse + fidelity_band
            and best_fill.node_count < best_stroke.node_count
        ):
            selected = best_fill
    ranked = (selected, *(item for item in ranked if item is not selected))
    competitor = next((item for item in ranked[1:] if item.kind is not selected.kind), None)
    margin = abs(competitor.score - selected.score) if competitor is not None else 1.0
    confidence = min(1.0, max(0.0, margin / max(minimum_confident_margin, 1.0e-9)))
    status = (
        RunStatus.NEEDS_REVIEW
        if routing.selected is RouteKind.AMBIGUOUS or margin < minimum_confident_margin
        else RunStatus.SUCCESS
    )
    return StrokeArbitration(selected, ranked, confidence, status, margin)
