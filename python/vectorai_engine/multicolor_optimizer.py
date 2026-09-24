"""Deterministic topology-fixed multicolor hypothesis refinement for E5."""

from __future__ import annotations

import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from vectorai_bench.metrics.editability import measure_svg_editability

from .continuous_scene import refine_palette_colors
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
    parameterization: str
    primitive_tolerance: float
    node_count: int
    analytic_fidelity: float
    objective_score: float


@dataclass(frozen=True, slots=True)
class OptimizationStageTiming:
    stage: str
    duration_ms: float


@dataclass(frozen=True, slots=True)
class MulticolorOptimizationResult:
    scene: MulticolorScene
    palette: PaletteResult
    svg: str
    selected_candidate_id: str
    profile_sha256: str
    baseline_node_count: int
    selected_node_count: int
    candidates: tuple[MulticolorHypothesisRecord, ...]
    rejected_tolerances: tuple[tuple[float, str], ...]
    render_rank: RenderRankResult
    stage_timings: tuple[OptimizationStageTiming, ...]
    continuous_iterations: int
    continuous_evaluations: int


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

    started = time.perf_counter()
    scene_selection_ms = 0.0
    export_editability_ms = 0.0
    objective_ms = 0.0
    continuous_refinement_ms = 0.0
    scenes: dict[str, MulticolorScene] = {}
    palettes: dict[str, PaletteResult] = {}
    svg_payloads: dict[str, str] = {}
    raw_records: list[tuple[str, str, float, int, float]] = []
    rejected: list[tuple[float, str]] = []
    with tempfile.TemporaryDirectory(prefix="vectorai-multicolor-opt-") as directory:
        root = Path(directory)
        for index, tolerance in enumerate(_candidate_tolerances(baseline_tolerance, profile)):
            candidate_id = f"tolerance-{tolerance:.6f}"
            selection_started = time.perf_counter()
            try:
                scene = select_multicolor_scene(
                    graph,
                    palette,
                    assembly,
                    primitive_tolerance=tolerance,
                    top_k=profile.limits.top_k,
                )
            except (EngineFailure, OSError, ValueError) as error:
                scene_selection_ms += (time.perf_counter() - selection_started) * 1000.0
                rejected.append((tolerance, type(error).__name__))
                continue
            scene_selection_ms += (time.perf_counter() - selection_started) * 1000.0
            export_started = time.perf_counter()
            try:
                svg_path = root / f"candidate-{index:04d}.svg"
                svg_payload, _ = export_multicolor_svg(scene, palette, svg_path)
                node_count = measure_svg_editability(svg_path).node_count
            except (EngineFailure, OSError, ValueError) as error:
                export_editability_ms += (time.perf_counter() - export_started) * 1000.0
                rejected.append((tolerance, type(error).__name__))
                continue
            export_editability_ms += (time.perf_counter() - export_started) * 1000.0
            cycle_count = sum(len(face.cycles) for face in scene.faces)
            average_error = scene.score.primitive_error / max(1, cycle_count)
            scenes[candidate_id] = scene
            palettes[candidate_id] = palette
            svg_payloads[candidate_id] = svg_payload
            raw_records.append((candidate_id, "geometry", tolerance, node_count, average_error))

    baseline_id = f"tolerance-{baseline_tolerance:.6f}"
    baseline_record = next((item for item in raw_records if item[0] == baseline_id), None)
    if baseline_record is None:
        raise ValueError("pre-optimization multicolor scene is not a valid candidate")
    baseline_nodes = baseline_record[3]
    refinement_started = time.perf_counter()
    refinement = refine_palette_colors(
        normalized,
        palette,
        profile,
        baseline_node_count=baseline_nodes,
    )
    continuous_refinement_ms = (time.perf_counter() - refinement_started) * 1000.0
    if (
        refinement.selected_analytic_rmse
        <= refinement.baseline_analytic_rmse - profile.limits.minimum_improvement
    ):
        continuous_id = "continuous-color"
        continuous_scene = scenes[baseline_id]
        continuous_svg, _ = export_multicolor_svg(
            continuous_scene,
            refinement.palette,
        )
        scenes[continuous_id] = continuous_scene
        palettes[continuous_id] = refinement.palette
        svg_payloads[continuous_id] = continuous_svg
        raw_records.append(
            (
                continuous_id,
                "continuous_color",
                baseline_tolerance,
                baseline_nodes,
                continuous_scene.score.primitive_error
                / max(1, sum(len(face.cycles) for face in continuous_scene.faces)),
            )
        )
    context = ObjectiveContext(normalized.width, normalized.height, baseline_nodes)
    records: list[MulticolorHypothesisRecord] = []
    candidates: list[RenderRankCandidate] = []
    objective_started = time.perf_counter()
    for candidate_id, parameterization, tolerance, node_count, average_error in raw_records:
        analytic_fidelity = (
            refinement.selected_analytic_rmse
            if parameterization == "continuous_color"
            else refinement.baseline_analytic_rmse
        )
        evaluation = evaluate_objective(
            RawObjectiveTerms(
                premultiplied_rgba_rmse=analytic_fidelity,
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
                parameterization,
                tolerance,
                node_count,
                analytic_fidelity,
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
    objective_ms = (time.perf_counter() - objective_started) * 1000.0
    reference = np.rint(np.clip(normalized.rgba_srgb, 0.0, 1.0) * 255.0).astype(np.uint8)
    render_started = time.perf_counter()
    ranked = render_and_rank_candidates(
        tuple(candidates),
        reference,
        profile.render_and_rank,
        top_k=profile.limits.top_k,
        resvg_executable=resvg_executable,
        resvg_command_prefix=resvg_command_prefix,
    )
    render_rank_ms = (time.perf_counter() - render_started) * 1000.0
    selected_id = ranked.winner_id
    selected_record = next(item for item in records if item.candidate_id == selected_id)
    total_ms = (time.perf_counter() - started) * 1000.0
    return MulticolorOptimizationResult(
        scene=scenes[selected_id],
        palette=palettes[selected_id],
        svg=svg_payloads[selected_id],
        selected_candidate_id=selected_id,
        profile_sha256=profile.sha256,
        baseline_node_count=baseline_nodes,
        selected_node_count=selected_record.node_count,
        candidates=tuple(records),
        rejected_tolerances=tuple(rejected),
        render_rank=ranked,
        continuous_iterations=refinement.optimization.iterations,
        continuous_evaluations=refinement.optimization.evaluations,
        stage_timings=(
            OptimizationStageTiming("scene_selection", scene_selection_ms),
            OptimizationStageTiming("export_editability", export_editability_ms),
            OptimizationStageTiming("continuous_refinement", continuous_refinement_ms),
            OptimizationStageTiming("objective", objective_ms),
            OptimizationStageTiming("render_rank", render_rank_ms),
            OptimizationStageTiming("total", total_ms),
        ),
    )
