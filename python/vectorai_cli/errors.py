"""CLI compatibility exports for the shared, typed engine error contract."""

from vectorai_engine.errors import (
    EngineError,
    EngineFailure,
    ErrorCode,
    RunStatus,
    Stage,
)

__all__ = [
    "EngineError",
    "EngineFailure",
    "ErrorCode",
    "RunStatus",
    "Stage",
]
