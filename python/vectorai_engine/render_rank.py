"""Bounded multi-scale/background resvg oracle for E5 Top-K candidates."""

from __future__ import annotations

import hashlib
import math
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import numpy.typing as npt
from PIL import Image

from vectorai_bench.external_tools import ToolStatus
from vectorai_bench.metrics.fidelity import (
    PreparedRGBA,
    premultiplied_rgba_rmse_prepared,
    prepare_rgba,
)
from vectorai_bench.renderers import ResvgAdapter

from .errors import EngineError, EngineFailure, ErrorCode, Stage
from .profiles import RenderAndRankProfile


@dataclass(frozen=True, slots=True)
class RenderRankCandidate:
    candidate_id: str
    svg: str
    node_count: int
    objective_score: float
    hard_valid: bool
    is_baseline: bool = False

    def __post_init__(self) -> None:
        if not self.candidate_id or not self.svg:
            raise ValueError("render-rank candidate ID and SVG must be nonempty")
        if self.node_count < 0 or not math.isfinite(self.objective_score):
            raise ValueError("render-rank candidate metrics are invalid")


@dataclass(frozen=True, slots=True)
class ScaleBackgroundScore:
    scale: float
    background: str
    premultiplied_rgba_rmse: float


@dataclass(frozen=True, slots=True)
class CandidateRenderScore:
    candidate_id: str
    aggregate_rmse: float
    node_count: int
    objective_score: float
    observations: tuple[ScaleBackgroundScore, ...]


@dataclass(frozen=True, slots=True)
class RenderRankResult:
    winner_id: str
    scores: tuple[CandidateRenderScore, ...]
    candidate_order: tuple[str, ...]
    unique_svg_count: int


def _failure(message: str) -> EngineFailure:
    return EngineFailure(
        EngineError(
            ErrorCode.RENDERER_DISAGREEMENT,
            Stage.RENDER_AND_RANK,
            message,
        )
    )


def _scaled_dimension(length: int, scale: float) -> int:
    if scale == 0.5:
        return max(1, (length + 1) // 2)
    if scale == 1.0:
        return length
    if scale == 2.0:
        return length * 2
    if scale == 4.0:
        return length * 4
    raise ValueError(f"unsupported render scale: {scale}")


def _resize_reference(
    reference: npt.NDArray[np.uint8],
    width: int,
    height: int,
) -> npt.NDArray[np.uint8]:
    if reference.ndim != 3 or reference.shape[2] != 4:
        raise ValueError("render-rank reference must be an RGBA image")
    image = Image.fromarray(reference, mode="RGBA")
    resized = image.resize((width, height), Image.Resampling.LANCZOS)
    return np.asarray(resized, dtype=np.uint8)


def _composite_lut() -> npt.NDArray[np.uint8]:
    channels = np.arange(256, dtype=np.float64) / 255.0
    alpha = channels
    backgrounds = np.asarray((0.0, 0.75, 0.95, 1.0), dtype=np.float64)
    values = (
        channels[None, None, :] * alpha[None, :, None]
        + backgrounds[:, None, None] * (1.0 - alpha[None, :, None])
    )
    return np.rint(np.clip(values, 0.0, 1.0) * 255.0).astype(np.uint8)


_OPAQUE_COMPOSITE_LUT = _composite_lut()


def _composite(
    rgba: npt.NDArray[np.uint8],
    background: str,
) -> npt.NDArray[np.uint8]:
    if background == "transparent":
        return rgba
    if background == "black":
        opaque_rgb = _OPAQUE_COMPOSITE_LUT[0, rgba[..., 3, None], rgba[..., :3]]
    elif background == "white":
        opaque_rgb = _OPAQUE_COMPOSITE_LUT[3, rgba[..., 3, None], rgba[..., :3]]
    elif background == "checkerboard":
        y, x = np.indices(rgba.shape[:2])
        checker_indices = np.asarray(1 + (x // 8 + y // 8) % 2, dtype=np.int64)
        opaque_rgb = _OPAQUE_COMPOSITE_LUT[
            checker_indices[..., None],
            rgba[..., 3, None],
            rgba[..., :3],
        ]
    else:
        raise ValueError(f"unsupported opaque background: {background}")
    opaque_alpha = np.full((*rgba.shape[:2], 1), 255, dtype=np.uint8)
    return np.concatenate((opaque_rgb, opaque_alpha), axis=2)


def score_rendered_candidate(
    candidate: RenderRankCandidate,
    reference_by_scale: dict[float, npt.NDArray[np.uint8]],
    rendered_by_scale: dict[float, npt.NDArray[np.uint8]],
    profile: RenderAndRankProfile,
    prepared_references: dict[tuple[float, str], PreparedRGBA] | None = None,
) -> CandidateRenderScore:
    observations: list[ScaleBackgroundScore] = []
    reference_cache = prepared_references if prepared_references is not None else {}
    for scale in profile.scales:
        reference = reference_by_scale[scale]
        rendered = rendered_by_scale[scale]
        if reference.shape != rendered.shape:
            raise ValueError("reference and candidate render dimensions differ")
        for background in profile.backgrounds:
            reference_key = (scale, background)
            prepared_reference = reference_cache.get(reference_key)
            if prepared_reference is None:
                prepared_reference = prepare_rgba(_composite(reference, background))
                reference_cache[reference_key] = prepared_reference
            rmse = premultiplied_rgba_rmse_prepared(
                prepared_reference,
                prepare_rgba(_composite(rendered, background)),
            )
            observations.append(
                ScaleBackgroundScore(
                    scale=scale,
                    background=background,
                    premultiplied_rgba_rmse=rmse,
                )
            )
    aggregate = sum(item.premultiplied_rgba_rmse for item in observations) / len(observations)
    return CandidateRenderScore(
        candidate_id=candidate.candidate_id,
        aggregate_rmse=aggregate,
        node_count=candidate.node_count,
        objective_score=candidate.objective_score,
        observations=tuple(observations),
    )


def render_and_rank_candidates(
    candidates: tuple[RenderRankCandidate, ...],
    reference_rgba: npt.NDArray[np.uint8],
    profile: RenderAndRankProfile,
    *,
    top_k: int,
    resvg_executable: Path | None = None,
    resvg_command_prefix: tuple[str, ...] | None = None,
) -> RenderRankResult:
    """Render only bounded hard-valid Top-K candidates and choose a stable winner."""

    if top_k < 1:
        raise ValueError("render-rank top_k must be positive")
    identities = tuple(candidate.candidate_id for candidate in candidates)
    if len(set(identities)) != len(identities):
        raise ValueError("render-rank candidate IDs must be unique")
    hard_valid = tuple(candidate for candidate in candidates if candidate.hard_valid)
    baselines = tuple(candidate for candidate in hard_valid if candidate.is_baseline)
    if len(baselines) > 1:
        raise ValueError("render-and-rank accepts at most one baseline candidate")
    ordered = sorted(
        (candidate for candidate in hard_valid if not candidate.is_baseline),
        key=lambda item: (item.objective_score, item.node_count, item.candidate_id),
    )
    eligible = list(baselines) + ordered[: max(0, top_k - len(baselines))]
    if not eligible:
        raise _failure("render-and-rank has no hard-valid candidate")

    height, width = reference_rgba.shape[:2]
    adapter = ResvgAdapter(
        executable=resvg_executable,
        command_prefix=resvg_command_prefix,
    )
    scores: list[CandidateRenderScore] = []
    with tempfile.TemporaryDirectory(prefix="vectorai-render-rank-") as directory:
        root = Path(directory)
        reference_by_scale: dict[float, npt.NDArray[np.uint8]] = {}
        dimensions: dict[float, tuple[int, int]] = {}
        for scale in profile.scales:
            scaled_width = _scaled_dimension(width, scale)
            scaled_height = _scaled_dimension(height, scale)
            dimensions[scale] = (scaled_width, scaled_height)
            reference_by_scale[scale] = _resize_reference(
                reference_rgba, scaled_width, scaled_height
            )
        rendered_cache: dict[str, dict[float, npt.NDArray[np.uint8]]] = {}
        score_cache: dict[str, CandidateRenderScore] = {}
        prepared_references: dict[tuple[float, str], PreparedRGBA] = {}
        for candidate_index, candidate in enumerate(eligible):
            svg_digest = hashlib.sha256(candidate.svg.encode("utf-8")).hexdigest()
            rendered_by_scale = rendered_cache.get(svg_digest)
            if rendered_by_scale is None:
                svg_path = root / f"candidate-{candidate_index:04d}.svg"
                try:
                    svg_path.write_text(candidate.svg, encoding="utf-8", newline="\n")
                except OSError as error:
                    raise _failure(f"cannot write render-rank candidate: {error}") from error
                rendered_by_scale = {}
                for scale_index, scale in enumerate(profile.scales):
                    scaled_width, scaled_height = dimensions[scale]
                    output_path = root / f"candidate-{candidate_index:04d}-{scale_index}.png"
                    result = adapter.render(
                        svg_path,
                        output_path,
                        width=scaled_width,
                        height=scaled_height,
                    )
                    if result.status is not ToolStatus.SUCCESS:
                        raise _failure(
                            result.message
                            or f"resvg failed for {candidate.candidate_id} at scale {scale}"
                        )
                    try:
                        with Image.open(output_path) as image:
                            rendered = np.asarray(image.convert("RGBA"), dtype=np.uint8)
                    except OSError as error:
                        raise _failure(f"cannot read resvg output: {error}") from error
                    rendered_by_scale[scale] = rendered
                rendered_cache[svg_digest] = rendered_by_scale
            cached_score = score_cache.get(svg_digest)
            if cached_score is None:
                candidate_score = score_rendered_candidate(
                    candidate,
                    reference_by_scale,
                    rendered_by_scale,
                    profile,
                    prepared_references,
                )
                score_cache[svg_digest] = candidate_score
            else:
                candidate_score = CandidateRenderScore(
                    candidate_id=candidate.candidate_id,
                    aggregate_rmse=cached_score.aggregate_rmse,
                    node_count=candidate.node_count,
                    objective_score=candidate.objective_score,
                    observations=cached_score.observations,
                )
            scores.append(candidate_score)
    best_rmse = min(item.aggregate_rmse for item in scores)

    def rank_key(item: CandidateRenderScore) -> tuple[int, float, float, float, str]:
        if item.aggregate_rmse <= best_rmse + profile.fidelity_band:
            return (
                0,
                item.node_count,
                item.aggregate_rmse,
                item.objective_score,
                item.candidate_id,
            )
        return (
            1,
            item.aggregate_rmse,
            item.node_count,
            item.objective_score,
            item.candidate_id,
        )

    ranked = tuple(sorted(scores, key=rank_key))
    return RenderRankResult(
        winner_id=ranked[0].candidate_id,
        scores=ranked,
        candidate_order=tuple(candidate.candidate_id for candidate in eligible),
        unique_svg_count=len(rendered_cache),
    )
