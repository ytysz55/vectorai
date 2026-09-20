"""Stable typed engine errors shared across Python and native boundaries."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class ErrorCode(StrEnum):
    UNSUPPORTED_INPUT = "UNSUPPORTED_INPUT"
    DECODE_ERROR = "DECODE_ERROR"
    RESOURCE_LIMIT = "RESOURCE_LIMIT"
    INVALID_COLOR_PROFILE = "INVALID_COLOR_PROFILE"
    AMBIGUOUS_ALPHA = "AMBIGUOUS_ALPHA"
    PALETTE_AMBIGUOUS = "PALETTE_AMBIGUOUS"
    TOPOLOGY_AMBIGUOUS = "TOPOLOGY_AMBIGUOUS"
    NON_MANIFOLD_GRAPH = "NON_MANIFOLD_GRAPH"
    INSUFFICIENT_BOUNDARY_EVIDENCE = "INSUFFICIENT_BOUNDARY_EVIDENCE"
    NO_FEASIBLE_CANDIDATE = "NO_FEASIBLE_CANDIDATE"
    STROKE_AMBIGUOUS = "STROKE_AMBIGUOUS"
    OPTIMIZER_DIVERGED = "OPTIMIZER_DIVERGED"
    EXPORT_FAILED = "EXPORT_FAILED"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    RENDERER_DISAGREEMENT = "RENDERER_DISAGREEMENT"
    INTERNAL_INVARIANT_VIOLATION = "INTERNAL_INVARIANT_VIOLATION"


class Stage(StrEnum):
    UNKNOWN = "unknown"
    DECODE = "decode"
    NORMALIZE = "normalize"
    RELIABILITY = "reliability"
    PALETTE = "palette"
    SEGMENTATION = "segmentation"
    TOPOLOGY = "topology"
    BOUNDARY = "boundary"
    CANDIDATE_GENERATION = "candidate_generation"
    STROKE = "stroke"
    MODEL_SELECTION = "model_selection"
    OPTIMIZATION = "optimization"
    RENDER_AND_RANK = "render_and_rank"
    EXPORT = "export"
    VALIDATION = "validation"


class RunStatus(StrEnum):
    SUCCESS = "success"
    DEGRADED = "degraded"
    NEEDS_REVIEW = "needs_review"
    UNSUPPORTED = "unsupported"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class EngineError:
    code: ErrorCode
    stage: Stage
    message: str
    retryable: bool = False
    entity_ids: tuple[int, ...] = ()
    context: dict[str, str] = field(default_factory=dict)


class EngineFailure(Exception):
    """Exception carrier used only inside Python; APIs expose its typed payload."""

    def __init__(self, error: EngineError) -> None:
        super().__init__(error.message)
        self.error = error
