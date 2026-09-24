"""Local-only HTTP API that never forwards source images to a remote service."""

# pyright: reportMissingImports=false

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request  # type: ignore[import-not-found, unused-ignore]
from fastapi.middleware.cors import CORSMiddleware  # type: ignore[import-not-found, unused-ignore]
from fastapi.responses import FileResponse  # type: ignore[import-not-found, unused-ignore]

from vectorai_engine.errors import EngineFailure, RunStatus
from vectorai_engine.multicolor_pipeline import (
    MulticolorPipelineConfig,
    run_multicolor_pipeline,
)
from vectorai_engine.stroke_pipeline import StrokePipelineConfig, run_stroke_pipeline

MAX_UPLOAD_BYTES = 32 * 1024 * 1024
JOB_ID_PATTERN = re.compile(r"^[a-f0-9]{64}-[a-f0-9]{12}$")
ARTIFACT_MEDIA_TYPES = {
    "output.svg": "image/svg+xml",
    "preview.png": "image/png",
    "scene.json": "application/json",
    "run-manifest.json": "application/json",
    "validation-report.json": "application/json",
    "events.jsonl": "application/x-ndjson",
    "cut-outline.svg": "image/svg+xml",
}


@dataclass(frozen=True, slots=True)
class ApiSettings:
    jobs_directory: Path
    resvg_executable: Path | None = None
    resvg_command_prefix: tuple[str, ...] | None = None
    max_upload_bytes: int = MAX_UPLOAD_BYTES


class ErrorPayload(TypedDict):
    code: str
    stage: str
    message: str


class VectorizeResponse(TypedDict):
    job_id: str
    status: str
    mode: str
    artifacts: dict[str, str]
    palette_count: int
    region_count: int
    seam_gap_rate: float


class HealthResponse(TypedDict):
    status: str
    local_only: bool


def _error(failure: EngineFailure) -> HTTPException:
    payload: ErrorPayload = {
        "code": failure.error.code.value,
        "stage": failure.error.stage.value,
        "message": failure.error.message,
    }
    return HTTPException(status_code=422, detail=payload)


def _job_path(settings: ApiSettings, job_id: str) -> Path:
    if not JOB_ID_PATTERN.fullmatch(job_id):
        raise HTTPException(status_code=404, detail="unknown job")
    candidate = (settings.jobs_directory / job_id).resolve()
    root = settings.jobs_directory.resolve()
    try:
        candidate.relative_to(root)
    except ValueError as error:
        raise HTTPException(status_code=404, detail="unknown job") from error
    return candidate


def _safe_filename(request: Request) -> str:
    provided = request.headers.get("x-vectorai-filename", "input.png")
    name = Path(provided).name
    if name.lower().endswith(".png"):
        return "input.png"
    if name.lower().endswith((".jpg", ".jpeg")):
        return "input.jpg"
    raise HTTPException(status_code=415, detail="only PNG and JPEG uploads are accepted")


async def read_bounded_body(request: Request, max_bytes: int) -> bytes:
    buffered = bytearray()
    async for chunk in request.stream():
        if len(buffered) + len(chunk) > max_bytes:
            raise HTTPException(status_code=413, detail="request exceeds local upload limit")
        buffered.extend(chunk)
    return bytes(buffered)


def create_app(settings: ApiSettings) -> FastAPI:
    if settings.max_upload_bytes < 1 or settings.max_upload_bytes > MAX_UPLOAD_BYTES:
        raise ValueError(f"max_upload_bytes must be in [1, {MAX_UPLOAD_BYTES}]")
    if settings.resvg_command_prefix is None and (
        settings.resvg_executable is None or not settings.resvg_executable.is_file()
    ):
        raise ValueError(f"resvg executable not found: {settings.resvg_executable}")
    settings.jobs_directory.mkdir(parents=True, exist_ok=True)
    app = FastAPI(
        title="VectorAI Local API",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:5173", "http://[::1]:5173"],
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["content-type", "x-vectorai-filename", "x-vectorai-mode"],
    )

    def health_response() -> HealthResponse:
        return {"status": "ready", "local_only": True}

    async def vectorize_response(request: Request) -> VectorizeResponse:
        length = request.headers.get("content-length")
        if length is not None:
            try:
                if int(length) > settings.max_upload_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail="request exceeds local upload limit",
                    )
            except ValueError as error:
                raise HTTPException(status_code=400, detail="invalid content-length") from error
        content_type = request.headers.get("content-type", "").split(";", 1)[0].lower()
        if content_type not in {"image/png", "image/jpeg"}:
            raise HTTPException(
                status_code=415,
                detail="content-type must be image/png or image/jpeg",
            )
        # Do not buffer an unbounded chunked request before enforcing the limit.
        source_bytes = await read_bounded_body(request, settings.max_upload_bytes)
        if not source_bytes:
            raise HTTPException(status_code=400, detail="request body is empty")
        if len(source_bytes) > settings.max_upload_bytes:
            raise HTTPException(status_code=413, detail="request exceeds local upload limit")
        mode = request.headers.get("x-vectorai-mode", "geometric").lower()
        if mode not in {"faithful", "geometric", "minimal", "stroke"}:
            raise HTTPException(status_code=400, detail="unknown vectorization mode")
        source_sha256 = hashlib.sha256(source_bytes).hexdigest()
        job_id = f"{source_sha256}-{uuid4().hex[:12]}"
        job_directory = _job_path(settings, job_id)
        input_path = job_directory / _safe_filename(request)
        try:
            job_directory.mkdir(parents=True, exist_ok=False)
            input_path.write_bytes(source_bytes)
        except OSError as error:
            raise HTTPException(
                status_code=500,
                detail="cannot store local upload",
            ) from error
        try:
            if mode == "stroke":
                stroke_bundle = run_stroke_pipeline(
                    input_path,
                    job_directory / "artifacts",
                    StrokePipelineConfig(
                        resvg_executable=settings.resvg_executable,
                        resvg_command_prefix=settings.resvg_command_prefix,
                    ),
                )
                scene = json.loads(stroke_bundle.scene_path.read_text(encoding="utf-8"))
                status = stroke_bundle.final_status
                palette_count = 1
                region_count = scene["graph"]["component_count"]
                seam_gap_rate = 0.0
                artifact_names = (*ARTIFACT_MEDIA_TYPES.keys(),)
            else:
                multicolor_bundle = run_multicolor_pipeline(
                    input_path,
                    job_directory / "artifacts",
                    MulticolorPipelineConfig(
                        resvg_executable=settings.resvg_executable,
                        resvg_command_prefix=settings.resvg_command_prefix,
                    ),
                )
                scene = json.loads(multicolor_bundle.scene_path.read_text(encoding="utf-8"))
                manifest = json.loads(multicolor_bundle.manifest_path.read_text(encoding="utf-8"))
                status = multicolor_bundle.final_status
                palette_count = scene["palette"]["selected_color_count"]
                region_count = scene["segmentation"]["region_count"]
                seam_gap_rate = max(
                    (item["transparent_gap_rate"] for item in manifest["seams"]["observations"]),
                    default=0.0,
                )
                artifact_names = tuple(
                    name for name in ARTIFACT_MEDIA_TYPES if name != "cut-outline.svg"
                )
        except EngineFailure as failure:
            raise _error(failure) from failure
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise HTTPException(
                status_code=500,
                detail="local pipeline failed",
            ) from error
        artifacts = {name: f"/v1/jobs/{job_id}/artifacts/{name}" for name in artifact_names}
        if status is RunStatus.FAILED:
            raise HTTPException(status_code=500, detail="local pipeline failed")
        return {
            "job_id": job_id,
            "status": status.value,
            "mode": mode,
            "artifacts": artifacts,
            "palette_count": palette_count,
            "region_count": region_count,
            "seam_gap_rate": seam_gap_rate,
        }

    def artifact_response(job_id: str, artifact_name: str) -> FileResponse:
        media_type = ARTIFACT_MEDIA_TYPES.get(artifact_name)
        if media_type is None:
            raise HTTPException(status_code=404, detail="unknown artifact")
        artifact_path = _job_path(settings, job_id) / "artifacts" / artifact_name
        if not artifact_path.is_file():
            raise HTTPException(status_code=404, detail="artifact does not exist")
        return FileResponse(artifact_path, media_type=media_type, filename=artifact_name)

    app.get("/health")(health_response)
    app.post("/v1/vectorize", responses={422: {"description": "engine failed"}})(vectorize_response)
    app.get("/v1/jobs/{job_id}/artifacts/{artifact_name}")(artifact_response)
    return app


def settings_from_environment() -> ApiSettings:
    root = Path(os.environ.get("VECTORAI_JOBS_DIR", "out/local-api-jobs"))
    resvg = os.environ.get("VECTORAI_RESVG")
    if resvg is None:
        raise ValueError("VECTORAI_RESVG must point to the pinned local resvg executable")
    return ApiSettings(jobs_directory=root, resvg_executable=Path(resvg))
