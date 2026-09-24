"""Privacy-safe structured events and schema-valid product run manifests."""

from __future__ import annotations

import hashlib
import json
import math
import platform
import re
import sys
from functools import lru_cache
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as package_version
from pathlib import Path
from typing import Any, cast

import psutil  # type: ignore[import-untyped]

from vectorai_bench.external_tools import ToolStatus, run_command

ENGINE_VERSION = "0.1.0"
_SCHEMA_VERSION = "1.0.0"
_ALLOWED_STAGES = frozenset(
    {
        "decode",
        "normalize",
        "reliability",
        "palette",
        "segmentation",
        "topology",
        "boundary",
        "candidate_generation",
        "stroke",
        "model_selection",
        "optimization",
        "render_and_rank",
        "export",
        "validation",
    }
)


def _json_bytes(payload: object) -> bytes:
    return (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


@lru_cache(maxsize=1)
def _build_identity() -> tuple[str, bool]:
    commit = run_command(("git", "rev-parse", "HEAD"), timeout_seconds=2.0)
    digest = commit.stdout.strip() if commit.status is ToolStatus.SUCCESS else ""
    if not re.fullmatch(r"[a-f0-9]{40}", digest):
        return ("0" * 40, True)
    dirty_check = run_command(
        ("git", "status", "--porcelain", "--untracked-files=no"), timeout_seconds=2.0
    )
    return digest, dirty_check.status is not ToolStatus.SUCCESS or bool(dirty_check.stdout)


def _rss_mb() -> float:
    info = psutil.Process().memory_info()
    observation = getattr(info, "peak_wset", info.rss)
    try:
        measured = float(observation)
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError("cannot measure process RSS") from error
    return max(0.0, measured / (1024.0 * 1024.0))


def stage_events(
    stage_durations: dict[str, float],
    *,
    fallback_code: str | None = None,
    debug_opt_in: bool = False,
    source_sha256: str | None = None,
) -> bytes:
    """Create ordered JSONL; default entries contain no path, image or user text."""

    events: list[dict[str, object]] = []
    for index, (stage, duration) in enumerate(stage_durations.items()):
        if stage not in _ALLOWED_STAGES or not math.isfinite(duration) or duration < 0.0:
            raise ValueError("unknown stage or non-finite stage duration")
        base: dict[str, object] = {
            "schema_version": _SCHEMA_VERSION,
            "stage": stage,
            "index": index,
        }
        if debug_opt_in and source_sha256 is not None:
            if not re.fullmatch(r"[a-f0-9]{64}", source_sha256):
                raise ValueError("debug source identity must be SHA-256")
            base["source_sha256"] = source_sha256
        events.append({**base, "code": "STAGE_STARTED"})
        events.append({**base, "code": "STAGE_COMPLETED", "duration_ms": duration})
    if fallback_code is not None:
        if not re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", fallback_code):
            raise ValueError("fallback code must be a stable identifier")
        events.append(
            {
                "schema_version": _SCHEMA_VERSION,
                "code": "FALLBACK_USED",
                "reason_code": fallback_code,
            }
        )
    return b"".join(_json_bytes(item) for item in events)


def _safe_findings(values: list[str], *, fallback: bool = False) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for value in values:
        code = (
            value
            if re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", value)
            else ("OPTIMIZER_FALLBACK" if fallback else "PIPELINE_WARNING")
        )
        result.append(
            {"code": code, "stage": "optimization" if fallback else "validation", "message": code}
        )
    return result


def _artifact(path: Path, root: Path, media_type: str) -> dict[str, object]:
    payload = path.read_bytes()
    return {
        "name": path.relative_to(root).as_posix(),
        "media_type": media_type,
        "sha256": hashlib.sha256(payload).hexdigest(),
        "bytes": len(payload),
    }


def full_run_manifest(
    legacy: dict[str, Any],
    *,
    stage_durations: dict[str, float],
    mode: str,
    event_path: Path,
    artifact_root: Path,
    fallback_code: str | None = None,
) -> dict[str, object]:
    """Preserve E3/E4 observations while adding the complete v1 manifest contract."""

    if mode not in {"faithful", "geometric", "minimal", "cut_ready"}:
        raise ValueError("unsupported manifest mode")
    config = legacy["configuration"]
    config_hash = hashlib.sha256(_json_bytes(config)).hexdigest()
    profile_hash = config.get("optimizer_profile_sha256") or config_hash
    if not re.fullmatch(r"[a-f0-9]{64}", profile_hash):
        raise ValueError("profile SHA-256 is invalid")
    commit, dirty = _build_identity()
    if sys.platform not in {"win32", "linux"}:
        raise ValueError("only Windows and Linux are supported")
    os_name = "windows" if sys.platform == "win32" else "linux"
    if platform.machine().lower() not in {"amd64", "x86_64"}:
        raise ValueError("only x86-64 is supported")
    dependencies: dict[str, str] = {"python": platform.python_version()}
    for package in ("numpy", "pillow", "psutil"):
        try:
            dependencies[package] = package_version(package)
        except PackageNotFoundError:
            continue
    renderer = legacy.get("renderer")
    if isinstance(renderer, dict):
        version = cast(dict[str, object], renderer).get("version")
        if isinstance(version, str) and version:
            dependencies["resvg"] = version
    for auxiliary in legacy.get("auxiliary_renderers", []):
        if not isinstance(auxiliary, dict):
            continue
        identity = cast(dict[str, object], auxiliary)
        name, observed_version = identity.get("name"), identity.get("version")
        if (
            name in {"inkscape", "chromium"}
            and isinstance(name, str)
            and isinstance(observed_version, str)
            and observed_version != "unknown"
        ):
            dependencies[name] = observed_version
    warnings = _safe_findings(list(legacy.get("warnings", [])))
    fallbacks = _safe_findings([fallback_code], fallback=True) if fallback_code else []
    artifacts: list[dict[str, object]] = []
    for item in legacy["artifacts"]:
        if isinstance(item, dict):
            artifacts.append(cast(dict[str, object], item))
        elif isinstance(item, str):
            media_type = (
                "image/svg+xml"
                if item.endswith(".svg")
                else ("image/png" if item.endswith(".png") else "application/json")
            )
            artifacts.append(_artifact(artifact_root / item, artifact_root, media_type))
    artifacts.append(_artifact(event_path, artifact_root, "application/x-ndjson"))
    stages = [
        {"name": stage, "status": "success", "duration_ms": duration}
        for stage, duration in stage_durations.items()
    ]
    summary = legacy.get("summary")
    if not isinstance(summary, dict):
        summary = {"regions": 0, "edges": 0, "candidates": 0, "optimizer_iterations": 0}
    enhanced: dict[str, object] = {
        **legacy,
        "engine": {
            "version": ENGINE_VERSION,
            "build_id": f"python-{commit[:12]}",
            "git_commit": commit,
            "dirty": dirty,
        },
        "configuration": {
            "config_sha256": config_hash,
            "profile_sha256": profile_hash,
            "profile_version": "1.0.0",
            "mode": mode,
            "seed": 0,
            "thread_count": 1,
            "determinism_policy": "strict",
            "parameters": config,
        },
        "platform": {
            "os": os_name,
            "arch": "x86_64",
            "cpu": platform.processor() or "unknown",
            "gpu": None,
            "compiler": "Python orchestration (no scene C++ compiler)",
        },
        "dependencies": dependencies,
        "stages": stages,
        "resources": {
            "total_duration_ms": legacy["total_duration_ms"],
            "peak_rss_mb": _rss_mb(),
        },
        "summary": summary,
        "warnings": warnings,
        "fallbacks": fallbacks,
        "artifacts": artifacts,
    }
    return enhanced
