"""Deterministic stroke branch, fill arbitration, and artifact bundle."""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray
from PIL import Image

from vectorai_bench.external_tools import ToolStatus
from vectorai_bench.metrics.editability import measure_svg_editability
from vectorai_bench.metrics.fidelity import compare_rgba
from vectorai_bench.metrics.topology import analyze_binary_mask
from vectorai_bench.renderers import ResvgAdapter

from .decode import DecodeLimits, decode_path
from .errors import EngineError, EngineFailure, ErrorCode, RunStatus, Stage
from .multicolor_pipeline import MulticolorPipelineConfig, run_multicolor_pipeline
from .normalize import NormalizedImage, normalize_source
from .stroke_graph import CenterlineGraph, build_centerline_graph
from .stroke_models import (
    estimate_width_profile,
    select_width_model,
    style_candidates,
)
from .stroke_routing import RoutingConfig, classify_fill_stroke
from .stroke_scene import export_stroke_svg, validate_cut_outline
from .stroke_selection import (
    HypothesisKind,
    StrokeCandidateEvaluation,
    arbitrate_fill_stroke,
    candidate_score,
)
from .topology_validation import raise_for_validation, validate_centerline_graph
from .validation_report import geometry_validation_report


@dataclass(frozen=True, slots=True)
class StrokePipelineConfig:
    resvg_executable: Path | None = None
    resvg_command_prefix: tuple[str, ...] | None = None
    decode_limits: DecodeLimits = field(default_factory=DecodeLimits)
    routing: RoutingConfig = field(default_factory=RoutingConfig)
    foreground_threshold: float = 0.5
    minimum_spur_length: float = 12.0
    maximum_constant_width_mae: float = 0.75
    maximum_relative_width_variation: float = 0.25
    complexity_weight: float = 5.0e-4
    minimum_confident_margin: float = 0.005


@dataclass(frozen=True, slots=True)
class StrokePipelineBundle:
    output_directory: Path
    svg_path: Path
    preview_path: Path
    cut_outline_path: Path
    scene_path: Path
    manifest_path: Path
    validation_path: Path
    final_status: RunStatus


def _failure(code: ErrorCode, stage: Stage, message: str) -> EngineFailure:
    return EngineFailure(EngineError(code, stage, message))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    try:
        path.write_text(
            json.dumps(payload, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    except (OSError, TypeError, ValueError) as error:
        raise _failure(
            ErrorCode.EXPORT_FAILED,
            Stage.EXPORT,
            f"cannot write JSON: {error}",
        ) from error


def _rgba(path: Path) -> NDArray[np.uint8]:
    try:
        with Image.open(path) as image:
            return np.asarray(image.convert("RGBA"), dtype=np.uint8)
    except OSError as error:
        raise _failure(
            ErrorCode.VALIDATION_FAILED,
            Stage.VALIDATION,
            f"cannot read rendered image: {error}",
        ) from error


def _stroke_mask(normalized: NormalizedImage, threshold: float) -> NDArray[np.bool_]:
    if not 0.0 < threshold < 1.0:
        raise ValueError("foreground_threshold must be inside (0, 1)")
    alpha = normalized.rgba_srgb[..., 3]
    if bool(np.any(alpha < 1.0 - 1.0e-6)):
        mask = alpha >= threshold
    else:
        mask = normalized.foreground_evidence >= threshold
    if not np.any(mask):
        raise _failure(ErrorCode.STROKE_AMBIGUOUS, Stage.STROKE, "stroke mask is empty")
    result: NDArray[np.bool_] = np.asarray(mask, dtype=np.bool_)
    return result


def _color_hex(rgba: NDArray[np.uint8], mask: NDArray[np.bool_]) -> str:
    try:
        channels = np.median(rgba[..., :3][mask], axis=0)
        values = tuple(round(float(channel)) for channel in channels)
    except (TypeError, ValueError, OverflowError, FloatingPointError) as error:
        raise _failure(
            ErrorCode.INTERNAL_INVARIANT_VIOLATION,
            Stage.STROKE,
            f"cannot estimate stroke color: {error}",
        ) from error
    return "#" + "".join(f"{min(255, max(0, value)):02x}" for value in values)


def _candidate_payload(candidate: StrokeCandidateEvaluation) -> dict[str, object]:
    return {
        "candidate_id": candidate.candidate_id,
        "kind": candidate.kind.value,
        "exact_topology": candidate.exact_topology,
        "premultiplied_rgba_rmse": candidate.premultiplied_rgba_rmse,
        "node_count": candidate.node_count,
        "score": candidate.score,
        "style": asdict(candidate.style) if candidate.style is not None else None,
    }


def _graph_payload(graph: CenterlineGraph) -> dict[str, object]:
    return {
        "component_count": graph.component_count,
        "removed_spur_count": graph.removed_spur_count,
        "nodes": [asdict(node) for node in graph.nodes],
        "edges": [
            {
                "edge_id": edge.edge_id,
                "start_node": edge.start_node,
                "end_node": edge.end_node,
                "point_count": len(edge.points),
                "points": [asdict(point) for point in edge.points],
                "length": edge.length,
            }
            for edge in graph.edges
        ],
    }


def _render_candidate(
    renderer: ResvgAdapter,
    svg_path: Path,
    preview_path: Path,
    *,
    width: int,
    height: int,
) -> None:
    rendered = renderer.render(svg_path, preview_path, width=width, height=height)
    if rendered.status is not ToolStatus.SUCCESS:
        raise _failure(
            ErrorCode.VALIDATION_FAILED,
            Stage.VALIDATION,
            rendered.message or f"resvg status: {rendered.status}",
        )


def run_stroke_pipeline(
    source_path: Path,
    output_directory: Path,
    config: StrokePipelineConfig,
) -> StrokePipelineBundle:
    if config.resvg_command_prefix is None and (
        config.resvg_executable is None or not config.resvg_executable.is_file()
    ):
        raise _failure(
            ErrorCode.UNSUPPORTED_INPUT,
            Stage.VALIDATION,
            f"resvg executable not found: {config.resvg_executable}",
        )
    if output_directory.exists():
        raise _failure(
            ErrorCode.EXPORT_FAILED,
            Stage.EXPORT,
            f"output directory already exists: {output_directory}",
        )
    source_path = source_path.resolve()
    if not source_path.is_file():
        raise _failure(ErrorCode.UNSUPPORTED_INPUT, Stage.DECODE, "input image does not exist")
    started = time.perf_counter()
    source = decode_path(source_path, limits=config.decode_limits)
    normalized = normalize_source(source)
    mask = _stroke_mask(normalized, config.foreground_threshold)
    routing = classify_fill_stroke(mask, config.routing)
    graph = build_centerline_graph(mask, minimum_spur_length=config.minimum_spur_length)
    if not graph.edges:
        raise _failure(ErrorCode.STROKE_AMBIGUOUS, Stage.STROKE, "stroke graph has no edges")
    geometry_result = validate_centerline_graph(graph)
    raise_for_validation(geometry_result)
    profile = estimate_width_profile(mask, graph)
    width_model = select_width_model(
        profile,
        graph,
        maximum_constant_mae=config.maximum_constant_width_mae,
        maximum_relative_variation=config.maximum_relative_width_variation,
    )
    foreground_topology = analyze_binary_mask(mask)
    stroke_topology_exact = graph.component_count == foreground_topology.components
    reference = source.rgba
    color = _color_hex(reference, mask)
    renderer = ResvgAdapter(
        executable=config.resvg_executable,
        command_prefix=config.resvg_command_prefix,
    )
    source_bytes = source_path.read_bytes()
    source_sha256 = hashlib.sha256(source_bytes).hexdigest()
    output_directory.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(prefix=f".{output_directory.name}-", dir=output_directory.parent)
    )
    try:
        fill_directory = temporary / "fill-candidate"
        fill_bundle = run_multicolor_pipeline(
            source_path,
            fill_directory,
            MulticolorPipelineConfig(
                resvg_executable=config.resvg_executable,
                resvg_command_prefix=config.resvg_command_prefix,
            ),
        )
        fill_scene = json.loads(fill_bundle.scene_path.read_text(encoding="utf-8"))
        fill_fidelity = compare_rgba(reference, _rgba(fill_bundle.preview_path))
        fill_nodes = measure_svg_editability(fill_bundle.svg_path).node_count
        fill_exact = (
            fill_scene["graph"]["foreground_component_count"] == foreground_topology.components
            and fill_scene["graph"]["hole_count"] == foreground_topology.holes
        )
        fill_score = candidate_score(
            kind=HypothesisKind.FILL,
            exact_topology=fill_exact,
            premultiplied_rgba_rmse=fill_fidelity.premultiplied_rgba_rmse,
            node_count=fill_nodes,
            routing=routing,
            complexity_weight=config.complexity_weight,
        )
        evaluations: list[StrokeCandidateEvaluation] = [
            StrokeCandidateEvaluation(
                "fill",
                HypothesisKind.FILL,
                fill_exact,
                fill_fidelity.premultiplied_rgba_rmse,
                fill_nodes,
                fill_score,
            )
        ]
        candidate_paths: dict[str, tuple[Path, Path]] = {
            "fill": (fill_bundle.svg_path, fill_bundle.preview_path)
        }
        candidate_directory = temporary / "stroke-candidates"
        for style in style_candidates():
            candidate_id = f"stroke-{style.cap.value}-{style.join.value}"
            svg_path = candidate_directory / f"{candidate_id}.svg"
            preview_path = candidate_directory / f"{candidate_id}.png"
            export_stroke_svg(
                graph,
                width_model,
                style,
                color=color,
                output_path=svg_path,
            )
            _render_candidate(
                renderer,
                svg_path,
                preview_path,
                width=source.width,
                height=source.height,
            )
            fidelity = compare_rgba(reference, _rgba(preview_path))
            nodes = measure_svg_editability(svg_path).node_count
            score = candidate_score(
                kind=HypothesisKind.STROKE,
                exact_topology=stroke_topology_exact,
                premultiplied_rgba_rmse=fidelity.premultiplied_rgba_rmse,
                node_count=nodes,
                routing=routing,
                complexity_weight=config.complexity_weight,
            )
            evaluations.append(
                StrokeCandidateEvaluation(
                    candidate_id,
                    HypothesisKind.STROKE,
                    stroke_topology_exact,
                    fidelity.premultiplied_rgba_rmse,
                    nodes,
                    score,
                    style,
                )
            )
            candidate_paths[candidate_id] = (svg_path, preview_path)
        arbitration = arbitrate_fill_stroke(
            tuple(evaluations),
            routing,
            minimum_confident_margin=config.minimum_confident_margin,
        )
        best_stroke = min(
            (item for item in evaluations if item.kind is HypothesisKind.STROKE),
            key=lambda item: (item.score, item.candidate_id),
        )
        if best_stroke.style is None:
            raise _failure(
                ErrorCode.INTERNAL_INVARIANT_VIOLATION,
                Stage.MODEL_SELECTION,
                "best stroke candidate has no style",
            )
        cut_outline_path = temporary / "cut-outline.svg"
        export_stroke_svg(
            graph,
            width_model,
            best_stroke.style,
            color=color,
            output_path=cut_outline_path,
            cut_outline=True,
        )
        cut_valid, cut_errors = validate_cut_outline(cut_outline_path)
        if not cut_valid:
            raise _failure(
                ErrorCode.VALIDATION_FAILED,
                Stage.VALIDATION,
                "; ".join(cut_errors),
            )
        selected_svg, selected_preview = candidate_paths[arbitration.selected.candidate_id]
        svg_path = temporary / "output.svg"
        preview_path = temporary / "preview.png"
        shutil.copy2(selected_svg, svg_path)
        shutil.copy2(selected_preview, preview_path)
        validation_path = temporary / "validation-report.json"
        _write_json(
            validation_path,
            geometry_validation_report(
                geometry_result,
                job_id=f"stroke-{source_sha256[:16]}",
                source_sha256=source_sha256,
                svg_bytes=svg_path.read_bytes(),
            ),
        )
        scene_path = temporary / "scene.json"
        _write_json(
            scene_path,
            {
                "schema_version": "1.0.0",
                "routing": asdict(routing),
                "graph": _graph_payload(graph),
                "width_profile": asdict(profile),
                "width_model": asdict(width_model),
                "arbitration": {
                    "selected": arbitration.selected.candidate_id,
                    "confidence": arbitration.confidence,
                    "score_margin": arbitration.score_margin,
                    "status": arbitration.status.value,
                    "ranked": [_candidate_payload(item) for item in arbitration.ranked],
                },
                "cut_outline_valid": cut_valid,
            },
        )
        manifest_path = temporary / "run-manifest.json"
        _write_json(
            manifest_path,
            {
                "schema_version": "1.0.0",
                "job_id": f"stroke-{source_sha256[:16]}",
                "input": {
                    "sha256": source_sha256,
                    "bytes": len(source_bytes),
                    "media_type": source.media_type,
                },
                "configuration": {
                    "routing": asdict(config.routing),
                    "foreground_threshold": config.foreground_threshold,
                    "minimum_spur_length": config.minimum_spur_length,
                    "maximum_constant_width_mae": config.maximum_constant_width_mae,
                    "maximum_relative_width_variation": (config.maximum_relative_width_variation),
                    "complexity_weight": config.complexity_weight,
                    "determinism_policy": "strict",
                },
                "selected_candidate": arbitration.selected.candidate_id,
                "best_stroke_candidate": best_stroke.candidate_id,
                "final_status": arbitration.status.value,
                "cut_outline_valid": cut_valid,
                "artifacts": [
                    "output.svg",
                    "preview.png",
                    "cut-outline.svg",
                    "scene.json",
                    "validation-report.json",
                ],
                "total_duration_ms": (time.perf_counter() - started) * 1000.0,
            },
        )
        temporary.replace(output_directory)
        return StrokePipelineBundle(
            output_directory,
            output_directory / svg_path.name,
            output_directory / preview_path.name,
            output_directory / cut_outline_path.name,
            output_directory / scene_path.name,
            output_directory / manifest_path.name,
            output_directory / validation_path.name,
            arbitration.status,
        )
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
