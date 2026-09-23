"""Deterministic topology-fixed multicolor hypothesis refinement for E5."""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from vectorai_bench.metrics.editability import measure_svg_editability

from .errors import EngineFailure
from .multicolor_graph import MulticolorRegionGraph
from .multicolor_scene import MulticolorScene, export_multicolor_svg, select_multicolor_scene
from .normalize import NormalizedImage
from .objectives import ObjectiveContext, RawObjectiveTerms, evaluate_objective
from .palette import PaletteResult
from .profiles import OptimizationProfile
from .render_rank import RenderRankCandidate, RenderRankResult, render_and_rank_candidates
from .shared_boundary import SharedBoundaryAssembly


@dataclass(frozen=True, slots=True)
class MulticolorHypothesisRecord:
    candidate_id: str
    primitive_tolerance: float
    node_count: int
    objective_score: float


@dataclass(frozen=True, slots=True)
class MulticolorOptimizationResult:
    scene: MulticolorScene
    svg: str
    selected_candidate_id: str
    profile_sha256: str
    baseline_node_count: int
    selected_node_count: int
    candidates: tuple[MulticolorHypothesisRecord, ...]
    rejected_tolerances: tuple[tuple[float, str], ...]
    render_rank: RenderRankResult


def _candidate_tolerances(baseline: float, profile: OptimizationProfile) -> tuple[float, ...]:
    maximum_delta = profile.limits.max_primitive_delta_px
    values = {baseline}
    for step in profile.limits.step_schedule:
        if step <= maximum_delta:
            values.add(max(0.0, baseline - step))
            values.add(baseline + step)
    return tuple(sorted(round(value, 6) for value in values))


def optimize_multicolor_hypotheses(
    graph: MulticolorRegionGraph,
    palette: PaletteResult,
    assembly: SharedBoundaryAssembly,
    normalized: NormalizedImage,
    *,
    baseline_tolerance: float,
    profile: OptimizationProfile,
    resvg_executable: Path | None = None,
    resvg_command_prefix: tuple[str, ...] | None = None,
) -> MulticolorOptimizationResult:
    """Rank topology-preserving tolerance hypotheses without rendering in the inner loop."""

    scenes: dict[str, MulticolorScene] = {}
    svg_payloads: dict[str, str] = {}
    raw_records: list[tuple[str, float, int, float]] = []
    rejected: list[tuple[float, str]] = []
    with tempfile.TemporaryDirectory(prefix="vectorai-multicolor-opt-") as directory:
        root = Path(directory)
        for index, tolerance in enumerate(_candidate_tolerances(baseline_tolerance, profile)):
            candidate_id = f"tolerance-{tolerance:.6f}"
            try:
                scene = select_multicolor_scene(
                    graph,
                    palette,
                    assembly,
                    primitive_tolerance=tolerance,
                    top_k=profile.limits.top_k,
                )
                svg_path = root / f"candidate-{index:04d}.svg"
                svg_payload, _ = export_multicolor_svg(scene, palette, svg_path)
                node_count = measure_svg_editability(svg_path).node_count
            except (EngineFailure, OSError, ValueError) as error:
                rejected.append((tolerance, type(error).__name__))
                continue
            cycle_count = sum(len(face.cycles) for face in scene.faces)
            average_error = scene.score.primitive_error / max(1, cycle_count)
            scenes[candidate_id] = scene
            svg_payloads[candidate_id] = svg_payload
            raw_records.append((candidate_id, tolerance, node_count, average_error))

    baseline_id = f"tolerance-{baseline_tolerance:.6f}"
    baseline_record = next((item for item in raw_records if item[0] == baseline_id), None)
    if baseline_record is None:
        raise ValueError("pre-optimization multicolor scene is not a valid candidate")
    baseline_nodes = baseline_record[2]
    context = ObjectiveContext(normalized.width, normalized.height, baseline_nodes)
    records: list[MulticolorHypothesisRecord] = []
    candidates: list[RenderRankCandidate] = []
    for candidate_id, tolerance, node_count, average_error in raw_records:
        evaluation = evaluate_objective(
            RawObjectiveTerms(
                premultiplied_rgba_rmse=0.0,
                boundary_rms_px=average_error,
                node_count=node_count,
                regularization_rms_px=average_error,
                color_rms=0.0,
            ),
            context,
            profile.weights.as_mapping(),
            hard_constraint_violations=("node_count_regressed",)
            if node_count > baseline_nodes
            else (),
        )
        if evaluation.weighted_score is None:
            continue
        records.append(
            MulticolorHypothesisRecord(
                candidate_id,
                tolerance,
                node_count,
                evaluation.weighted_score,
            )
        )
        candidates.append(
            RenderRankCandidate(
                candidate_id,
                svg_payloads[candidate_id],
                node_count,
                evaluation.weighted_score,
                True,
                candidate_id == baseline_id,
            )
        )
    reference = np.rint(np.clip(normalized.rgba_srgb, 0.0, 1.0) * 255.0).astype(np.uint8)
    ranked = render_and_rank_candidates(
        tuple(candidates),
        reference,
        profile.render_and_rank,
        top_k=profile.limits.top_k,
        resvg_executable=resvg_executable,
        resvg_command_prefix=resvg_command_prefix,
    )
    selected_id = ranked.winner_id
    selected_record = next(item for item in records if item.candidate_id == selected_id)
    return MulticolorOptimizationResult(
        scene=scenes[selected_id],
        svg=svg_payloads[selected_id],
        selected_candidate_id=selected_id,
        profile_sha256=profile.sha256,
        baseline_node_count=baseline_nodes,
        selected_node_count=selected_record.node_count,
        candidates=tuple(records),
        rejected_tolerances=tuple(rejected),
        render_rank=ranked,
    )
