"""Local deterministic orchestration for the E3 multicolor reconstruction path."""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from vectorai_bench.external_tools import ToolStatus
from vectorai_bench.metrics.topology import analyze_binary_mask
from vectorai_bench.renderers import ResvgAdapter
from vectorai_bench.svg_validation import ChromiumAdapter, InkscapeAdapter

from .decode import DecodeLimits, decode_path
from .errors import EngineError, EngineFailure, ErrorCode, RunStatus, Stage
from .junctions import analyze_junction_hypotheses
from .multicolor_graph import build_multicolor_region_graph
from .multicolor_optimizer import optimize_multicolor_hypotheses
from .multicolor_scene import export_multicolor_svg, select_multicolor_scene
from .normalize import normalize_source
from .palette import PaletteConfig, generate_palette_hypotheses
from .profiles import OptimizationMode, load_optimizer_profiles
from .reliability import analyze_reliability
from .segmentation import SpatialSegmentationConfig, segment_multicolor
from .shared_boundary import assemble_shared_boundaries, measure_renderer_seams
from .topology_validation import raise_for_validation, validate_multicolor_output
from .validation_report import geometry_validation_report


@dataclass(frozen=True, slots=True)
class MulticolorPipelineConfig:
    resvg_executable: Path | None = None
    resvg_command_prefix: tuple[str, ...] | None = None
    inkscape_command_prefix: tuple[str, ...] | None = None
    chromium_command_prefix: tuple[str, ...] | None = None
    require_auxiliary_renderers: bool = False
    palette: PaletteConfig = field(default_factory=PaletteConfig)
    segmentation: SpatialSegmentationConfig = field(default_factory=SpatialSegmentationConfig)
    decode_limits: DecodeLimits = field(default_factory=DecodeLimits)
    primitive_tolerance: float = 0.75
    optimizer_profile_path: Path | None = None
    optimizer_mode: OptimizationMode = OptimizationMode.GEOMETRIC


@dataclass(frozen=True, slots=True)
class MulticolorPipelineBundle:
    output_directory: Path
    svg_path: Path
    preview_path: Path
    manifest_path: Path
    scene_path: Path
    validation_path: Path
    final_status: RunStatus


def _failure(code: ErrorCode, stage: Stage, message: str) -> EngineFailure:
    return EngineFailure(EngineError(code, stage, message))


def _json_bytes(payload: object) -> bytes:
    return (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _write_json(path: Path, payload: object) -> None:
    try:
        path.write_bytes(_json_bytes(payload))
    except OSError as error:
        raise _failure(
            ErrorCode.EXPORT_FAILED,
            Stage.EXPORT,
            f"cannot write {path.name}: {error}",
        ) from error


def _artifact(path: Path, root: Path, media_type: str) -> dict[str, object]:
    try:
        content = path.read_bytes()
    except OSError as error:
        raise _failure(
            ErrorCode.EXPORT_FAILED,
            Stage.EXPORT,
            f"cannot read {path.name}: {error}",
        ) from error
    return {
        "name": path.relative_to(root).as_posix(),
        "media_type": media_type,
        "sha256": hashlib.sha256(content).hexdigest(),
        "bytes": len(content),
    }


def run_multicolor_pipeline(
    source_path: Path,
    output_directory: Path,
    config: MulticolorPipelineConfig,
) -> MulticolorPipelineBundle:
    if config.resvg_command_prefix is None and (
        config.resvg_executable is None or not config.resvg_executable.is_file()
    ):
        raise _failure(
            ErrorCode.UNSUPPORTED_INPUT,
            Stage.VALIDATION,
            f"resvg executable not found: {config.resvg_executable}",
        )
    if config.require_auxiliary_renderers and (
        config.inkscape_command_prefix is None or config.chromium_command_prefix is None
    ):
        raise _failure(
            ErrorCode.UNSUPPORTED_INPUT,
            Stage.VALIDATION,
            "required Inkscape and Chromium commands were not configured",
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
    durations: dict[str, float] = {}

    decode_started = time.perf_counter()
    source = decode_path(source_path, limits=config.decode_limits)
    durations["decode"] = (time.perf_counter() - decode_started) * 1000.0
    normalize_started = time.perf_counter()
    normalized = normalize_source(source)
    durations["normalize"] = (time.perf_counter() - normalize_started) * 1000.0
    reliability_started = time.perf_counter()
    reliability = analyze_reliability(normalized)
    durations["reliability"] = (time.perf_counter() - reliability_started) * 1000.0
    palette_started = time.perf_counter()
    palette = generate_palette_hypotheses(normalized, reliability, config.palette)
    durations["palette"] = (time.perf_counter() - palette_started) * 1000.0
    segmentation_started = time.perf_counter()
    segmentation = segment_multicolor(
        normalized,
        palette.selected,
        reliability,
        config.segmentation,
    )
    durations["segmentation"] = (time.perf_counter() - segmentation_started) * 1000.0
    topology_started = time.perf_counter()
    graph = build_multicolor_region_graph(segmentation)
    junctions = analyze_junction_hypotheses(graph, segmentation)
    assembly = assemble_shared_boundaries(graph, segmentation, junctions)
    durations["topology"] = (time.perf_counter() - topology_started) * 1000.0
    model_started = time.perf_counter()
    scene = select_multicolor_scene(
        graph,
        palette,
        assembly,
        primitive_tolerance=config.primitive_tolerance,
    )
    durations["model_selection"] = (time.perf_counter() - model_started) * 1000.0

    source_bytes = source_path.read_bytes()
    source_sha256 = hashlib.sha256(source_bytes).hexdigest()
    output_directory.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(prefix=f".{output_directory.name}-", dir=output_directory.parent)
    )
    try:
        optimizer_manifest: dict[str, object] | None = None
        optimizer_degraded = False
        optimizer_fallback_reason: str | None = None
        if config.optimizer_profile_path is not None:
            optimization_started = time.perf_counter()
            try:
                profile_set = load_optimizer_profiles(config.optimizer_profile_path)
                profile = profile_set.select(config.optimizer_mode)
                optimization = optimize_multicolor_hypotheses(
                    graph,
                    palette,
                    assembly,
                    normalized,
                    baseline_tolerance=config.primitive_tolerance,
                    profile=profile,
                    resvg_executable=config.resvg_executable,
                    resvg_command_prefix=config.resvg_command_prefix,
                )
            except Exception as error:
                optimizer_degraded = True
                optimizer_fallback_reason = (
                    error.error.code.value
                    if isinstance(error, EngineFailure)
                    else type(error).__name__
                )
                optimizer_manifest = {
                    "status": "degraded",
                    "fallback_used": True,
                    "fallback_reason": optimizer_fallback_reason,
                    "mode": config.optimizer_mode.value,
                }
            else:
                scene = optimization.scene
                palette = optimization.palette
                optimizer_manifest = {
                    "status": "success",
                    "fallback_used": False,
                    "profile_set_sha256": profile_set.sha256,
                    "profile_sha256": optimization.profile_sha256,
                    "mode": profile.mode.value,
                    "selected_candidate_id": optimization.selected_candidate_id,
                    "baseline_node_count": optimization.baseline_node_count,
                    "selected_node_count": optimization.selected_node_count,
                    "candidates": [asdict(item) for item in optimization.candidates],
                    "rejected_tolerances": [
                        list(item) for item in optimization.rejected_tolerances
                    ],
                    "render_rank": asdict(optimization.render_rank),
                    "stage_timings": [asdict(item) for item in optimization.stage_timings],
                }
            durations["optimization"] = (time.perf_counter() - optimization_started) * 1000.0
        geometry_result = validate_multicolor_output(graph, assembly, scene)
        raise_for_validation(geometry_result)
        svg_path = temporary / "output.svg"
        export_started = time.perf_counter()
        _, scene_manifest = export_multicolor_svg(scene, palette, svg_path)
        durations["export"] = (time.perf_counter() - export_started) * 1000.0
        validation_path = temporary / "validation-report.json"
        _write_json(
            validation_path,
            geometry_validation_report(
                geometry_result,
                job_id=f"multicolor-{source_sha256[:16]}",
                source_sha256=source_sha256,
                svg_bytes=svg_path.read_bytes(),
            ),
        )
        scene_path = temporary / "scene.json"
        foreground_topology = analyze_binary_mask(palette.selected.labels >= 0)
        _write_json(
            scene_path,
            {
                "schema_version": "1.0.0",
                "palette": {
                    "selected_color_count": palette.selected.color_count,
                    "colors": [asdict(color) for color in palette.selected.colors],
                    "hypotheses": [
                        {
                            "color_count": item.color_count,
                            "weighted_sse": item.weighted_sse,
                            "model_score": item.model_score,
                        }
                        for item in palette.hypotheses
                    ],
                },
                "segmentation": {
                    "region_count": len(segmentation.regions),
                    "iterations_run": segmentation.iterations_run,
                },
                "graph": {
                    "face_count": len(graph.faces) - 1,
                    "hole_count": foreground_topology.holes,
                    "foreground_component_count": foreground_topology.components,
                    "adjacency": sorted(graph.adjacency),
                    "canonical_edge_count": graph.canonical_edge_count,
                },
                "junctions": [asdict(item) for item in junctions],
                "shared_boundaries": {
                    "seam_pairs": [asdict(item) for item in assembly.seam_pairs],
                    "canonical_edge_count": len(assembly.segments),
                },
                "scene": scene_manifest,
                "optimizer": optimizer_manifest,
            },
        )
        preview_path = temporary / "preview.png"
        validation_started = time.perf_counter()
        rendered = ResvgAdapter(
            executable=config.resvg_executable,
            command_prefix=config.resvg_command_prefix,
        ).render(
            svg_path,
            preview_path,
            width=source.width,
            height=source.height,
        )
        if rendered.status is not ToolStatus.SUCCESS:
            raise _failure(
                ErrorCode.VALIDATION_FAILED,
                Stage.VALIDATION,
                rendered.message or f"resvg status: {rendered.status}",
            )
        renderer_outputs = {"resvg": preview_path}
        auxiliary_results: list[dict[str, object]] = []
        auxiliary_artifacts: list[Path] = []
        auxiliary_adapters = (
            (
                "inkscape",
                InkscapeAdapter(command_prefix=config.inkscape_command_prefix)
                if config.inkscape_command_prefix is not None
                else None,
            ),
            (
                "chromium",
                ChromiumAdapter(command_prefix=config.chromium_command_prefix)
                if config.chromium_command_prefix is not None
                else None,
            ),
        )
        for renderer_name, adapter in auxiliary_adapters:
            if adapter is None:
                continue
            renderer_path = temporary / f"preview-{renderer_name}.png"
            auxiliary = adapter.render(
                svg_path,
                renderer_path,
                width=source.width,
                height=source.height,
            )
            auxiliary_results.append(
                {
                    "name": renderer_name,
                    "status": auxiliary.status.value,
                    "version": auxiliary.identity.version if auxiliary.identity else "unknown",
                    "output_sha256": auxiliary.output_sha256,
                    "message": auxiliary.message,
                }
            )
            if auxiliary.status is ToolStatus.SUCCESS:
                renderer_outputs[renderer_name] = renderer_path
                auxiliary_artifacts.append(renderer_path)
            elif config.require_auxiliary_renderers:
                raise _failure(
                    ErrorCode.VALIDATION_FAILED,
                    Stage.VALIDATION,
                    auxiliary.message or f"{renderer_name} status: {auxiliary.status}",
                )
        seam_matrix = measure_renderer_seams(assembly, renderer_outputs)
        durations["validation"] = (time.perf_counter() - validation_started) * 1000.0
        gap_rate = max(
            (item.transparent_gap_rate for item in seam_matrix.observations),
            default=0.0,
        )
        final_status = (
            RunStatus.NEEDS_REVIEW
            if gap_rate > 0.0 or geometry_result.needs_review
            else RunStatus.DEGRADED
            if optimizer_degraded
            else RunStatus.SUCCESS
        )
        manifest_path = temporary / "run-manifest.json"
        _write_json(
            manifest_path,
            {
                "schema_version": "1.0.0",
                "job_id": f"multicolor-{source_sha256[:16]}",
                "input": {
                    "sha256": source_sha256,
                    "bytes": len(source_bytes),
                    "media_type": source.media_type,
                },
                "configuration": {
                    "palette": asdict(config.palette),
                    "segmentation": asdict(config.segmentation),
                    "primitive_tolerance": config.primitive_tolerance,
                    "optimizer_mode": config.optimizer_mode.value
                    if config.optimizer_profile_path is not None
                    else None,
                    "optimizer_profile_sha256": optimizer_manifest.get("profile_sha256")
                    if optimizer_manifest is not None
                    else None,
                    "determinism_policy": "strict",
                },
                "stages": [
                    {"name": name, "duration_ms": value} for name, value in durations.items()
                ],
                "renderer": {
                    "name": "resvg",
                    "version": rendered.identity.version if rendered.identity else "unknown",
                    "output_sha256": rendered.output_sha256,
                },
                "auxiliary_renderers": auxiliary_results,
                "seams": asdict(seam_matrix),
                "warnings": [
                    *normalized.warnings,
                    *(
                        (f"optimizer fallback: {optimizer_fallback_reason}",)
                        if optimizer_fallback_reason is not None
                        else ()
                    ),
                ],
                "final_status": final_status.value,
                "artifacts": [
                    _artifact(svg_path, temporary, "image/svg+xml"),
                    _artifact(preview_path, temporary, "image/png"),
                    _artifact(scene_path, temporary, "application/json"),
                    _artifact(validation_path, temporary, "application/json"),
                    *(_artifact(path, temporary, "image/png") for path in auxiliary_artifacts),
                ],
                "total_duration_ms": (time.perf_counter() - started) * 1000.0,
            },
        )
        temporary.replace(output_directory)
        return MulticolorPipelineBundle(
            output_directory=output_directory,
            svg_path=output_directory / svg_path.name,
            preview_path=output_directory / preview_path.name,
            manifest_path=output_directory / manifest_path.name,
            scene_path=output_directory / scene_path.name,
            validation_path=output_directory / validation_path.name,
            final_status=final_status,
        )
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
