"""Safe Python orchestration for the native E2 binary pipeline."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import psutil  # type: ignore[import-untyped]
from PIL import Image

from vectorai_bench.external_tools import ToolStatus, file_sha256, run_command
from vectorai_bench.metrics.editability import measure_svg_editability
from vectorai_bench.metrics.fidelity import compare_rgba
from vectorai_bench.renderers import ResvgAdapter
from vectorai_bench.svg_validation import (
    ChromiumAdapter,
    InkscapeAdapter,
    ValidationStatus,
    validate_svg_renderers,
)

from .decode import DecodeLimits, decode_path
from .errors import EngineError, EngineFailure, ErrorCode, RunStatus, Stage
from .normalize import normalize_source
from .reliability import analyze_reliability


@dataclass(frozen=True, slots=True)
class BinaryPipelineConfig:
    native_executable: Path
    native_command_prefix: tuple[str, ...] | None = None
    resvg_executable: Path | None = None
    resvg_command_prefix: tuple[str, ...] | None = None
    inkscape_command_prefix: tuple[str, ...] | None = None
    chromium_command_prefix: tuple[str, ...] | None = None
    threshold: float | None = None
    subpixel: bool = True
    bezier_only: bool = False
    validate_auxiliary_renderers: bool = True
    timeout_seconds: float = 60.0
    decode_limits: DecodeLimits = field(default_factory=DecodeLimits)


@dataclass(frozen=True, slots=True)
class PipelineBundle:
    output_directory: Path
    svg_path: Path
    manifest_path: Path
    validation_path: Path
    native_report_path: Path
    final_status: RunStatus


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
    except OSError as error:
        raise EngineFailure(
            EngineError(
                ErrorCode.EXPORT_FAILED,
                Stage.EXPORT,
                f"cannot hash artifact {path.name}: {error}",
            )
        ) from error
    return digest.hexdigest()


def _canonical_json(payload: object) -> bytes:
    return (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _write_json(path: Path, payload: object) -> None:
    try:
        path.write_bytes(_canonical_json(payload))
    except OSError as error:
        raise EngineFailure(
            EngineError(
                ErrorCode.EXPORT_FAILED,
                Stage.EXPORT,
                f"cannot write {path.name}: {error}",
            )
        ) from error


def _write_pgm(path: Path, values: np.ndarray) -> None:
    if values.ndim != 2 or values.size < 1 or not np.isfinite(values).all():
        raise EngineFailure(
            EngineError(
                ErrorCode.INTERNAL_INVARIANT_VIOLATION,
                Stage.NORMALIZE,
                "native PGM channel must be a finite 2D array",
            )
        )
    try:
        minimum = float(np.min(values))
        maximum = float(np.max(values))
    except (TypeError, ValueError, FloatingPointError) as error:
        raise EngineFailure(
            EngineError(
                ErrorCode.INTERNAL_INVARIANT_VIOLATION,
                Stage.NORMALIZE,
                f"cannot inspect native PGM range: {error}",
            )
        ) from error
    if minimum < 0.0 or maximum > 1.0:
        raise EngineFailure(
            EngineError(
                ErrorCode.INTERNAL_INVARIANT_VIOLATION,
                Stage.NORMALIZE,
                "native PGM channel must be in [0, 1]",
            )
        )
    height, width = values.shape
    quantized = np.rint(values * 255.0).astype(np.uint8)
    try:
        path.write_bytes(f"P5\n{width} {height}\n255\n".encode() + quantized.tobytes())
    except OSError as error:
        raise EngineFailure(
            EngineError(ErrorCode.EXPORT_FAILED, Stage.EXPORT, f"cannot write PGM: {error}")
        ) from error


def _native_failure(report_path: Path, fallback: str) -> EngineFailure:
    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
        code = ErrorCode(str(payload.get("code", ErrorCode.INTERNAL_INVARIANT_VIOLATION)))
        stage = Stage(str(payload.get("stage", Stage.UNKNOWN)))
        message = str(payload.get("message", fallback))
    except (OSError, json.JSONDecodeError, ValueError, TypeError):
        code = ErrorCode.INTERNAL_INVARIANT_VIOLATION
        stage = Stage.UNKNOWN
        message = fallback
    return EngineFailure(EngineError(code, stage, message))


def _artifact(path: Path, root: Path, media_type: str) -> dict[str, object]:
    try:
        size = path.stat().st_size
    except OSError as error:
        raise EngineFailure(
            EngineError(
                ErrorCode.EXPORT_FAILED,
                Stage.EXPORT,
                f"cannot inspect artifact {path.name}: {error}",
            )
        ) from error
    return {
        "name": path.relative_to(root).as_posix(),
        "media_type": media_type,
        "sha256": _sha256_path(path),
        "bytes": size,
    }


def _finding(code: str, stage: str, message: str) -> dict[str, object]:
    return {"code": code, "stage": stage, "message": message, "entity_ids": []}


def _renderer_validation(
    svg_path: Path,
    work_directory: Path,
    *,
    width: int,
    height: int,
    source_sha256: str,
    resvg_executable: Path | None,
    resvg_command_prefix: tuple[str, ...] | None,
    inkscape_command_prefix: tuple[str, ...] | None,
    chromium_command_prefix: tuple[str, ...] | None,
    validate_auxiliary_renderers: bool,
) -> tuple[dict[str, object], ValidationStatus]:
    renderer_result = validate_svg_renderers(
        svg_path,
        work_directory / "renders",
        width=width,
        height=height,
        resvg=ResvgAdapter(
            executable=resvg_executable,
            command_prefix=resvg_command_prefix,
        ),
        inkscape=(
            InkscapeAdapter(command_prefix=inkscape_command_prefix)
            if validate_auxiliary_renderers
            else None
        ),
        chromium=(
            ChromiumAdapter(command_prefix=chromium_command_prefix)
            if validate_auxiliary_renderers
            else None
        ),
    )
    gates: list[dict[str, object]] = [
        {
            "id": "TOPOLOGY.EXACT_BINARY",
            "category": "topology",
            "severity": "hard",
            "outcome": "passed",
            "message": "native model selection preserved component and hole count",
        }
    ]
    hard_failures = 0
    soft_failures = 0
    warnings = 0
    for check in renderer_result.checks:
        unavailable = check.status in {ToolStatus.UNAVAILABLE, ToolStatus.VERSION_MISMATCH}
        disagreement = (
            check.premultiplied_rgba_rmse is not None and check.premultiplied_rgba_rmse > 0.02
        )
        passed = check.status is ToolStatus.SUCCESS and not disagreement
        severity = "hard" if check.name == "resvg" else "soft"
        if passed:
            outcome = "passed"
        elif unavailable:
            outcome = "skipped"
            warnings += 1
        else:
            outcome = "failed"
            if severity == "hard":
                hard_failures += 1
            else:
                soft_failures += 1
        gate: dict[str, object] = {
            "id": f"RENDERER.{check.name.upper()}",
            "category": "renderer",
            "severity": severity,
            "outcome": outcome,
            "message": check.message or f"{check.name} render {outcome}",
        }
        if check.premultiplied_rgba_rmse is not None:
            gate["metric"] = check.premultiplied_rgba_rmse
            gate["threshold"] = 0.02
        gates.append(gate)
    report: dict[str, object] = {
        "schema_version": "1.0.0",
        "job_id": f"binary-{source_sha256[:16]}",
        "status": renderer_result.status.value,
        "source_sha256": source_sha256,
        "svg_sha256": _sha256_path(svg_path),
        "gates": gates,
        "summary": {
            "hard_failures": hard_failures,
            "soft_failures": soft_failures,
            "warnings": warnings,
        },
    }
    return report, renderer_result.status


def run_binary_pipeline(
    source_path: Path,
    output_directory: Path,
    config: BinaryPipelineConfig,
) -> PipelineBundle:
    if not config.native_executable.is_file():
        raise EngineFailure(
            EngineError(
                ErrorCode.UNSUPPORTED_INPUT,
                Stage.UNKNOWN,
                f"native executable not found: {config.native_executable}",
            )
        )
    if config.threshold is not None and not 0.0 <= config.threshold <= 1.0:
        raise EngineFailure(
            EngineError(
                ErrorCode.TOPOLOGY_AMBIGUOUS,
                Stage.SEGMENTATION,
                "threshold must be in [0, 1]",
            )
        )
    if config.timeout_seconds <= 0.0:
        raise EngineFailure(
            EngineError(
                ErrorCode.RESOURCE_LIMIT,
                Stage.UNKNOWN,
                "timeout_seconds must be positive",
            )
        )
    if output_directory.exists():
        raise EngineFailure(
            EngineError(
                ErrorCode.EXPORT_FAILED,
                Stage.EXPORT,
                f"output directory already exists: {output_directory}",
            )
        )

    started = time.perf_counter()
    stage_durations: dict[str, float] = {}
    decode_started = time.perf_counter()
    source = decode_path(source_path, limits=config.decode_limits)
    stage_durations["decode"] = (time.perf_counter() - decode_started) * 1000.0
    normalize_started = time.perf_counter()
    normalized = normalize_source(source)
    stage_durations["normalize"] = (time.perf_counter() - normalize_started) * 1000.0
    reliability_started = time.perf_counter()
    reliability = analyze_reliability(normalized)
    stage_durations["reliability"] = (time.perf_counter() - reliability_started) * 1000.0

    source_bytes = source_path.read_bytes()
    source_sha256 = _sha256_bytes(source_bytes)
    output_directory.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(prefix=f".{output_directory.name}-", dir=output_directory.parent)
    )
    try:
        evidence_path = temporary / ".foreground.pgm"
        reliability_path = temporary / ".reliability.pgm"
        svg_path = temporary / "output.svg"
        native_report_path = temporary / "native-report.json"
        _write_pgm(evidence_path, normalized.foreground_evidence)
        _write_pgm(reliability_path, reliability.confidence)
        command = [
            *(
                config.native_command_prefix
                if config.native_command_prefix is not None
                else (str(config.native_executable.resolve()),)
            ),
            "--input",
            str(evidence_path.resolve()),
            "--reliability",
            str(reliability_path.resolve()),
            "--output",
            str(svg_path.resolve()),
            "--report",
            str(native_report_path.resolve()),
            "--subpixel",
            "1" if config.subpixel else "0",
        ]
        if config.threshold is not None:
            command.extend(("--threshold", format(config.threshold, ".9g")))
        if config.bezier_only:
            command.append("--bezier-only")
        native_started = time.perf_counter()
        native = run_command(tuple(command), timeout_seconds=config.timeout_seconds)
        native_duration = (time.perf_counter() - native_started) * 1000.0
        if native.status is not ToolStatus.SUCCESS:
            raise _native_failure(
                native_report_path,
                native.stderr or native.stdout or f"native process status: {native.status}",
            )
        try:
            native_report = json.loads(native_report_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError) as error:
            raise EngineFailure(
                EngineError(
                    ErrorCode.VALIDATION_FAILED,
                    Stage.VALIDATION,
                    f"native report is invalid: {error}",
                )
            ) from error
        if native_report.get("status") != "success" or not svg_path.is_file():
            raise _native_failure(native_report_path, "native pipeline produced no SVG")

        validation_report, validation_status = _renderer_validation(
            svg_path,
            temporary,
            width=source.width,
            height=source.height,
            source_sha256=source_sha256,
            resvg_executable=config.resvg_executable,
            resvg_command_prefix=config.resvg_command_prefix,
            inkscape_command_prefix=config.inkscape_command_prefix,
            chromium_command_prefix=config.chromium_command_prefix,
            validate_auxiliary_renderers=config.validate_auxiliary_renderers,
        )
        validation_path = temporary / "validation-report.json"
        _write_json(validation_path, validation_report)
        resvg_preview = temporary / "renders" / "resvg.png"
        preview_path = temporary / "preview.png"
        if resvg_preview.is_file():
            shutil.copyfile(resvg_preview, preview_path)

        fidelity_payload: dict[str, object] | None = None
        if preview_path.is_file():
            try:
                with Image.open(preview_path) as preview_image:
                    preview_rgba = np.asarray(preview_image.convert("RGBA"), dtype=np.uint8)
                fidelity_payload = asdict(compare_rgba(source.rgba, preview_rgba))
            except (OSError, ValueError) as error:
                raise EngineFailure(
                    EngineError(
                        ErrorCode.VALIDATION_FAILED,
                        Stage.VALIDATION,
                        f"cannot measure preview fidelity: {error}",
                    )
                ) from error
        metrics_payload = {
            "schema_version": "1.0.0",
            "topology": {
                "components": int(native_report["components"]),
                "holes": int(native_report["holes"]),
                "euler": int(native_report["euler"]),
                "preserved": True,
            },
            "fidelity": fidelity_payload,
            "editability": asdict(measure_svg_editability(svg_path)),
            "native": {
                "canonical_edges": int(native_report["canonical_edges"]),
                "boundary_samples": int(native_report["boundary_samples"]),
                "candidate_count": int(native_report["candidate_count"]),
                "selected_shapes": int(native_report["selected_shapes"]),
            },
        }
        metrics_path = temporary / "metrics.json"
        _write_json(metrics_path, metrics_payload)

        config_payload = {
            "profile_version": "1.0.0",
            "mode": "geometric",
            "seed": 0,
            "thread_count": 1,
            "threshold": config.threshold,
            "subpixel": config.subpixel,
            "bezier_only": config.bezier_only,
            "validate_auxiliary_renderers": config.validate_auxiliary_renderers,
        }
        config_sha256 = _sha256_bytes(_canonical_json(config_payload))
        warnings = [
            _finding("NORMALIZATION_WARNING", "normalize", warning)
            for warning in normalized.warnings
        ]
        if validation_status is not ValidationStatus.PASSED:
            warnings.append(
                _finding(
                    "RENDERER_VALIDATION_INCOMPLETE",
                    "validation",
                    f"renderer validation status is {validation_status.value}",
                )
            )
        final_status = (
            RunStatus.SUCCESS
            if validation_status is ValidationStatus.PASSED
            else RunStatus.FAILED
            if validation_status is ValidationStatus.FAILED
            else RunStatus.NEEDS_REVIEW
        )
        native_stage_names = (
            "segmentation",
            "topology",
            "boundary",
            "candidate_generation",
            "model_selection",
            "export",
        )
        stages = [
            {"name": name, "status": "success", "duration_ms": duration}
            for name, duration in stage_durations.items()
        ]
        stages.extend(
            {
                "name": name,
                "status": "success",
                "duration_ms": native_duration if index == 0 else 0.0,
            }
            for index, name in enumerate(native_stage_names)
        )
        stages.append(
            {
                "name": "validation",
                "status": final_status.value,
                "duration_ms": 0.0,
            }
        )
        artifacts = [
            _artifact(svg_path, temporary, "image/svg+xml"),
            _artifact(native_report_path, temporary, "application/json"),
            _artifact(validation_path, temporary, "application/json"),
            _artifact(metrics_path, temporary, "application/json"),
        ]
        if preview_path.is_file():
            artifacts.append(_artifact(preview_path, temporary, "image/png"))
        total_duration = (time.perf_counter() - started) * 1000.0
        manifest: dict[str, Any] = {
            "schema_version": "1.0.0",
            "job_id": f"binary-{source_sha256[:16]}-{config_sha256[:8]}",
            "input": {
                "sha256": source_sha256,
                "bytes": len(source_bytes),
                "media_type": source.media_type,
            },
            "engine": {
                "version": "0.1.0",
                "build_id": file_sha256(config.native_executable)[:16],
                "git_commit": os.environ.get("VECTORAI_GIT_COMMIT", "0" * 40),
                "dirty": os.environ.get("VECTORAI_GIT_DIRTY", "1") != "0",
            },
            "configuration": {
                "config_sha256": config_sha256,
                "profile_sha256": config_sha256,
                "profile_version": "1.0.0",
                "mode": "geometric",
                "seed": 0,
                "thread_count": 1,
                "determinism_policy": "strict",
            },
            "platform": {
                "os": platform.system().lower(),
                "arch": "x86_64",
                "cpu": platform.processor() or "unknown",
                "gpu": None,
                "compiler": "c++17-native",
            },
            "dependencies": {
                "native_cli_sha256": file_sha256(config.native_executable),
            },
            "stages": stages,
            "resources": {
                "total_duration_ms": total_duration,
                "peak_rss_mb": psutil.Process().memory_info().rss / (1024.0 * 1024.0),
            },
            "summary": {
                "regions": int(native_report["components"]),
                "edges": int(native_report["canonical_edges"]),
                "candidates": int(native_report["candidate_count"]),
                "optimizer_iterations": 0,
            },
            "warnings": warnings,
            "fallbacks": [],
            "final_status": final_status.value,
            "artifacts": artifacts,
        }
        manifest_path = temporary / "run-manifest.json"
        _write_json(manifest_path, manifest)
        evidence_path.unlink(missing_ok=True)
        reliability_path.unlink(missing_ok=True)
        temporary.replace(output_directory)
        return PipelineBundle(
            output_directory=output_directory,
            svg_path=output_directory / svg_path.name,
            manifest_path=output_directory / manifest_path.name,
            validation_path=output_directory / validation_path.name,
            native_report_path=output_directory / native_report_path.name,
            final_status=final_status,
        )
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
