"""Strict loading and canonical hashing for E5 optimizer profiles."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from itertools import pairwise
from pathlib import Path
from typing import cast

from .objectives import OBJECTIVE_NORMALIZATION_VERSION, TERM_NAMES

PROFILE_SCHEMA_VERSION = "1.0.0"
OPTIMIZER_PROFILE_PATH = Path(__file__).with_name("optimizer-profiles-v1.json")
_SEMVER = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
_EXPECTED_SCALES = (0.5, 1.0, 2.0, 4.0)
_EXPECTED_BACKGROUNDS = ("transparent", "black", "white", "checkerboard")


class OptimizationMode(StrEnum):
    FAITHFUL = "faithful"
    GEOMETRIC = "geometric"
    MINIMAL = "minimal"
    CUT_READY = "cut_ready"


@dataclass(frozen=True, slots=True)
class ObjectiveWeights:
    fidelity: float
    boundary: float
    complexity: float
    regularization: float
    color: float

    def as_mapping(self) -> dict[str, float]:
        return {
            "fidelity": self.fidelity,
            "boundary": self.boundary,
            "complexity": self.complexity,
            "regularization": self.regularization,
            "color": self.color,
        }


@dataclass(frozen=True, slots=True)
class OptimizationLimits:
    max_iterations: int
    max_evaluations: int
    top_k: int
    early_stop_patience: int
    minimum_improvement: float
    step_schedule: tuple[float, ...]
    max_vertex_delta_px: float
    max_primitive_delta_px: float
    max_color_delta: float
    max_width_delta_px: float
    minimum_positive_geometry: float


@dataclass(frozen=True, slots=True)
class RenderAndRankProfile:
    scales: tuple[float, ...]
    backgrounds: tuple[str, ...]
    fidelity_band: float


@dataclass(frozen=True, slots=True)
class OptimizationProfile:
    profile_version: str
    mode: OptimizationMode
    weights: ObjectiveWeights
    limits: OptimizationLimits
    render_and_rank: RenderAndRankProfile
    sha256: str


@dataclass(frozen=True, slots=True)
class OptimizerProfileSet:
    schema_version: str
    normalization_version: str
    profiles: tuple[OptimizationProfile, ...]
    sha256: str

    def select(self, mode: OptimizationMode | str) -> OptimizationProfile:
        selected_mode = OptimizationMode(mode)
        for profile in self.profiles:
            if profile.mode is selected_mode:
                return profile
        raise ValueError(f"optimizer profile is missing mode: {selected_mode.value}")


def canonical_json_bytes(payload: object) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _object(value: object, context: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{context} must be an object with string keys")
    untyped = cast(dict[object, object], value)
    if not all(isinstance(key, str) for key in untyped):
        raise ValueError(f"{context} must be an object with string keys")
    return {cast(str, key): item for key, item in untyped.items()}


def _exact_keys(value: Mapping[str, object], expected: set[str], context: str) -> None:
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        unknown = sorted(actual - expected)
        raise ValueError(f"{context} keys differ; missing={missing}, unknown={unknown}")


def _string(value: object, context: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{context} must be a nonempty string")
    return value


def _number(value: object, context: str, *, minimum: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{context} must be numeric")
    try:
        result = float(value)
    except (OverflowError, ValueError) as error:
        raise ValueError(f"{context} cannot be represented as a finite number") from error
    if not math.isfinite(result) or result < minimum:
        raise ValueError(f"{context} must be finite and at least {minimum}")
    return result


def _integer(value: object, context: str, *, minimum: int = 1) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{context} must be an integer at least {minimum}")
    return value


def _weights(value: object) -> ObjectiveWeights:
    payload = _object(value, "weights")
    _exact_keys(payload, set(TERM_NAMES), "weights")
    values = {name: _number(payload[name], f"weights.{name}") for name in TERM_NAMES}
    if any(item > 1.0 for item in values.values()):
        raise ValueError("objective weights must not exceed one")
    if not math.isclose(sum(values.values()), 1.0, rel_tol=0.0, abs_tol=1.0e-12):
        raise ValueError("objective weights must sum to one")
    return ObjectiveWeights(**values)


def _limits(value: object) -> OptimizationLimits:
    expected = {
        "max_iterations",
        "max_evaluations",
        "top_k",
        "early_stop_patience",
        "minimum_improvement",
        "step_schedule",
        "max_vertex_delta_px",
        "max_primitive_delta_px",
        "max_color_delta",
        "max_width_delta_px",
        "minimum_positive_geometry",
    }
    payload = _object(value, "limits")
    _exact_keys(payload, expected, "limits")
    schedule_value = payload["step_schedule"]
    if not isinstance(schedule_value, list) or not schedule_value:
        raise ValueError("limits.step_schedule must be a nonempty array")
    schedule_items = cast(list[object], schedule_value)
    schedule = tuple(
        _number(item, f"limits.step_schedule[{index}]", minimum=1.0e-15)
        for index, item in enumerate(schedule_items)
    )
    if any(left <= right for left, right in pairwise(schedule)):
        raise ValueError("limits.step_schedule must be strictly decreasing")
    max_iterations = _integer(payload["max_iterations"], "limits.max_iterations")
    max_evaluations = _integer(payload["max_evaluations"], "limits.max_evaluations")
    if max_evaluations < max_iterations:
        raise ValueError("limits.max_evaluations must cover max_iterations")
    max_color_delta = _number(payload["max_color_delta"], "limits.max_color_delta")
    if max_color_delta > 1.0:
        raise ValueError("limits.max_color_delta must not exceed one")
    return OptimizationLimits(
        max_iterations=max_iterations,
        max_evaluations=max_evaluations,
        top_k=_integer(payload["top_k"], "limits.top_k"),
        early_stop_patience=_integer(payload["early_stop_patience"], "limits.early_stop_patience"),
        minimum_improvement=_number(
            payload["minimum_improvement"],
            "limits.minimum_improvement",
            minimum=1.0e-15,
        ),
        step_schedule=schedule,
        max_vertex_delta_px=_number(payload["max_vertex_delta_px"], "limits.max_vertex_delta_px"),
        max_primitive_delta_px=_number(
            payload["max_primitive_delta_px"], "limits.max_primitive_delta_px"
        ),
        max_color_delta=max_color_delta,
        max_width_delta_px=_number(payload["max_width_delta_px"], "limits.max_width_delta_px"),
        minimum_positive_geometry=_number(
            payload["minimum_positive_geometry"],
            "limits.minimum_positive_geometry",
            minimum=1.0e-15,
        ),
    )


def _render_and_rank(value: object) -> RenderAndRankProfile:
    payload = _object(value, "render_and_rank")
    _exact_keys(payload, {"scales", "backgrounds", "fidelity_band"}, "render_and_rank")
    scales_value = payload["scales"]
    backgrounds_value = payload["backgrounds"]
    if not isinstance(scales_value, list) or not isinstance(backgrounds_value, list):
        raise ValueError("render-and-rank scales and backgrounds must be arrays")
    scale_items = cast(list[object], scales_value)
    background_items = cast(list[object], backgrounds_value)
    scales = tuple(
        _number(item, f"render_and_rank.scales[{index}]", minimum=1.0e-15)
        for index, item in enumerate(scale_items)
    )
    if scales != _EXPECTED_SCALES:
        raise ValueError(f"render-and-rank scales must be {_EXPECTED_SCALES}")
    if not all(isinstance(item, str) for item in background_items):
        raise ValueError("render-and-rank backgrounds must be strings")
    backgrounds = tuple(cast(str, item) for item in background_items)
    if backgrounds != _EXPECTED_BACKGROUNDS:
        raise ValueError(f"render-and-rank backgrounds must be {_EXPECTED_BACKGROUNDS}")
    fidelity_band = _number(payload["fidelity_band"], "render_and_rank.fidelity_band")
    if fidelity_band > 1.0:
        raise ValueError("render-and-rank fidelity band must not exceed one")
    return RenderAndRankProfile(
        scales=scales,
        backgrounds=backgrounds,
        fidelity_band=fidelity_band,
    )


def _profile(value: object) -> OptimizationProfile:
    payload = _object(value, "profile")
    _exact_keys(
        payload,
        {"profile_version", "mode", "weights", "limits", "render_and_rank"},
        "profile",
    )
    version = _string(payload["profile_version"], "profile.profile_version")
    if _SEMVER.fullmatch(version) is None:
        raise ValueError("profile.profile_version must use semantic version syntax")
    mode = OptimizationMode(_string(payload["mode"], "profile.mode"))
    digest = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
    return OptimizationProfile(
        profile_version=version,
        mode=mode,
        weights=_weights(payload["weights"]),
        limits=_limits(payload["limits"]),
        render_and_rank=_render_and_rank(payload["render_and_rank"]),
        sha256=digest,
    )


def load_optimizer_profiles(path: Path) -> OptimizerProfileSet:
    try:
        raw_bytes = path.read_bytes()
        decoded = cast(object, json.loads(raw_bytes))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot load optimizer profiles: {error}") from error
    payload = _object(decoded, "optimizer profile set")
    _exact_keys(
        payload,
        {"schema_version", "normalization_version", "profiles"},
        "optimizer profile set",
    )
    schema_version = _string(payload["schema_version"], "schema_version")
    if schema_version != PROFILE_SCHEMA_VERSION:
        raise ValueError(f"unsupported optimizer profile schema: {schema_version}")
    normalization_version = _string(payload["normalization_version"], "normalization_version")
    if normalization_version != OBJECTIVE_NORMALIZATION_VERSION:
        raise ValueError(f"unsupported objective normalization: {normalization_version}")
    profiles_value = payload["profiles"]
    if not isinstance(profiles_value, list):
        raise ValueError("profiles must be an array")
    profile_items = cast(list[object], profiles_value)
    profiles = tuple(_profile(item) for item in profile_items)
    expected_modes = tuple(OptimizationMode)
    if tuple(profile.mode for profile in profiles) != expected_modes:
        raise ValueError(f"profiles must appear exactly once in order: {expected_modes}")
    return OptimizerProfileSet(
        schema_version=schema_version,
        normalization_version=normalization_version,
        profiles=profiles,
        sha256=hashlib.sha256(canonical_json_bytes(payload)).hexdigest(),
    )
