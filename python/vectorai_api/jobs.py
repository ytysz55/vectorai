"""Single-process local job supervisor with durable, fail-closed status publication."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import threading
from collections import deque
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from uuid import uuid4

import psutil  # type: ignore[import-untyped]

JOB_ID_PATTERN = re.compile(r"^[a-f0-9]{64}-[a-f0-9]{12}$")
TERMINAL = frozenset({"success", "degraded", "needs_review", "unsupported", "failed", "canceled"})
PUBLISHED = frozenset({"success", "degraded", "needs_review"})
ARTIFACTS = (
    "output.svg",
    "preview.png",
    "scene.json",
    "run-manifest.json",
    "validation-report.json",
    "events.jsonl",
    "cut-outline.svg",
)


class JobBusyError(Exception):
    """The bounded local queue is full."""


class IdempotencyConflictError(Exception):
    """One key must never identify two distinct requests."""


class IdempotencyStoreError(Exception):
    """The persisted key index cannot be reconstructed safely."""


@dataclass(slots=True)
class _Job:
    job_id: str
    directory: Path
    record: dict[str, object]
    process: subprocess.Popen[bytes] | None = None
    thread: threading.Thread | None = None
    cancel_requested: bool = False


def _utc() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _error(code: str, *, retryable: bool) -> dict[str, object]:
    return {
        "code": code,
        "stage": "job",
        "message": "Local job did not produce a validated output.",
        "retryable": retryable,
    }


def _atomic_json(path: Path, payload: dict[str, object]) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _read_json(path: Path) -> dict[str, object]:
    if path.stat().st_size > 1024 * 1024:
        raise ValueError("job status exceeds the 1 MiB budget")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("cannot read job status") from error
    if not isinstance(payload, dict):
        raise ValueError("job status must be an object")
    return cast(dict[str, object], payload)


def _stop_process(process: subprocess.Popen[bytes]) -> None:
    """Kill the worker and its renderer descendants; only call for owned PIDs."""
    with suppress(psutil.NoSuchProcess, psutil.AccessDenied):
        parent = psutil.Process(process.pid)
        children = parent.children(recursive=True)
        for child in children:
            with suppress(psutil.NoSuchProcess, psutil.AccessDenied):
                child.kill()
        with suppress(psutil.NoSuchProcess, psutil.AccessDenied):
            parent.kill()
        psutil.wait_procs(children, timeout=2.0)
    try:
        process.wait(timeout=5.0)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5.0)


class JobManager:
    def __init__(
        self,
        root: Path,
        *,
        resvg_executable: Path | None,
        resvg_command_prefix: tuple[str, ...] | None,
        max_job_seconds: float,
        max_queued_jobs: int = 2,
    ) -> None:
        if max_job_seconds <= 0:
            raise ValueError("max_job_seconds must be positive")
        if max_queued_jobs < 0 or max_queued_jobs > 16:
            raise ValueError("max_queued_jobs must be in [0, 16]")
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.resvg_executable = resvg_executable.resolve() if resvg_executable else None
        self.resvg_command_prefix = resvg_command_prefix
        self.max_job_seconds = max_job_seconds
        self.max_queued_jobs = max_queued_jobs
        self.lock = threading.RLock()
        self.jobs: dict[str, _Job] = {}
        self.active: str | None = None
        self.queued: deque[str] = deque()
        self.idempotency: dict[str, tuple[str, str]] = {}
        self.conflicted_keys: set[str] = set()
        self.idempotency_ready = True
        self.closing = False
        self._recover()

    def _directory(self, job_id: str) -> Path:
        if not JOB_ID_PATTERN.fullmatch(job_id):
            raise FileNotFoundError("unknown job")
        candidate = (self.root / job_id).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError as error:
            raise FileNotFoundError("unknown job") from error
        return candidate

    def _recover(self) -> None:
        for path in self.root.iterdir():
            if not path.is_dir() or not JOB_ID_PATTERN.fullmatch(path.name):
                continue
            try:
                status_path = self._directory(path.name) / "job-status.json"
                if not status_path.is_file():
                    continue
                record = _read_json(status_path)
                if record.get("job_id") != path.name:
                    raise ValueError("persisted job ID disagrees with its directory")
            except (OSError, ValueError):
                if (path / "idempotency.json").exists():
                    self.idempotency_ready = False
                continue
            identity = status_path.with_name("idempotency.json")
            if identity.is_file():
                try:
                    saved = _read_json(identity)
                    key_hash, fingerprint = saved.get("key_hash"), saved.get("fingerprint")
                    if (
                        not isinstance(key_hash, str)
                        or not isinstance(fingerprint, str)
                        or not re.fullmatch(r"[a-f0-9]{64}", key_hash)
                        or not re.fullmatch(r"[a-f0-9]{64}", fingerprint)
                    ):
                        raise ValueError("persisted idempotency identity is invalid")
                    previous = self.idempotency.get(key_hash)
                    if previous is not None and previous != (path.name, fingerprint):
                        self.conflicted_keys.add(key_hash)
                    else:
                        self.idempotency[key_hash] = (path.name, fingerprint)
                except (OSError, ValueError):
                    self.idempotency_ready = False
            if record.get("state") in {"accepted", "running"}:
                record.update(
                    {
                        "state": "failed",
                        "cancel_requested": False,
                        "completed_at": _utc(),
                        "error": _error("JOB_INTERRUPTED", retryable=True),
                    }
                )
                try:
                    _atomic_json(status_path, record)
                except OSError:
                    self.idempotency_ready = False

    def _save(self, job: _Job) -> None:
        _atomic_json(job.directory / "job-status.json", job.record)

    def _launch(self, job: _Job) -> None:
        self.active = job.job_id
        try:
            thread = threading.Thread(
                target=self._run, args=(job,), name="vectorai-job", daemon=True
            )
            job.thread = thread
            thread.start()
        except RuntimeError:
            self._final(job, "failed", error=_error("JOB_START_FAILED", retryable=True))

    def _final(self, job: _Job, state: str, *, error: dict[str, object] | None = None) -> None:
        job.record.update({"state": state, "completed_at": _utc(), "cancel_requested": False})
        if error is not None:
            job.record["error"] = error
        self._save(job)
        self.jobs.pop(job.job_id, None)
        if job.job_id in self.queued:
            self.queued.remove(job.job_id)
        if self.active == job.job_id:
            self.active = None
        if not self.closing and self.active is None and self.queued:
            next_id = self.queued.popleft()
            self._launch(self.jobs[next_id])

    def submit(
        self,
        payload: bytes,
        *,
        input_name: str,
        mode: str,
        idempotency_key: str | None = None,
    ) -> dict[str, object]:
        if input_name not in {"input.png", "input.jpg"} or mode not in {"geometric", "stroke"}:
            raise ValueError("unsupported job input or mode")
        source_hash = hashlib.sha256(payload).hexdigest()
        key_hash: str | None = None
        fingerprint = hashlib.sha256(f"{source_hash}\0{mode}\0{input_name}".encode()).hexdigest()
        if idempotency_key is not None:
            if not re.fullmatch(r"[\x21-\x7e]{1,128}", idempotency_key):
                raise ValueError("invalid idempotency key")
            key_hash = hashlib.sha256(idempotency_key.encode("ascii")).hexdigest()
        with self.lock:
            if self.closing:
                raise JobBusyError("local service is shutting down")
            if key_hash is not None:
                if not self.idempotency_ready:
                    raise IdempotencyStoreError("persisted idempotency history is damaged")
                if key_hash in self.conflicted_keys:
                    raise IdempotencyConflictError("idempotency history is ambiguous")
                previous = self.idempotency.get(key_hash)
                if previous is not None:
                    if previous[1] != fingerprint:
                        raise IdempotencyConflictError("key was used for a different request")
                    return self.status(previous[0])
            if self.active is not None and len(self.queued) >= self.max_queued_jobs:
                raise JobBusyError("local job queue is full")
            job_id = f"{source_hash}-{uuid4().hex[:12]}"
            directory = self._directory(job_id)
            directory.mkdir(parents=True, exist_ok=False)
            try:
                (directory / input_name).write_bytes(payload)
                _atomic_json(
                    directory / "worker-config.json",
                    {
                        "mode": mode,
                        "input_name": input_name,
                        "resvg_executable": (
                            str(self.resvg_executable) if self.resvg_executable else None
                        ),
                        "resvg_command_prefix": list(self.resvg_command_prefix)
                        if self.resvg_command_prefix
                        else None,
                    },
                )
                record: dict[str, object] = {
                    "schema_version": "1.0.0",
                    "job_id": job_id,
                    "state": "accepted",
                    "mode": mode,
                    "input_sha256": source_hash,
                    "config_sha256": hashlib.sha256(f"api-v1:{mode}".encode()).hexdigest(),
                    "engine_build_id": None,
                    "created_at": _utc(),
                    "started_at": None,
                    "completed_at": None,
                    "cancel_requested": False,
                    "artifacts": {},
                    "error": None,
                    "palette_count": None,
                    "region_count": None,
                    "seam_gap_rate": None,
                }
                job = _Job(job_id, directory, record)
                self._save(job)
                if key_hash is not None:
                    _atomic_json(
                        directory / "idempotency.json",
                        {
                            "key_hash": key_hash,
                            "fingerprint": fingerprint,
                        },
                    )
                self.jobs[job_id] = job
                if key_hash is not None:
                    self.idempotency[key_hash] = (job_id, fingerprint)
                if self.active is None:
                    self._launch(job)
                else:
                    self.queued.append(job_id)
                return dict(job.record)
            except (OSError, RuntimeError):
                self.jobs.pop(job_id, None)
                if key_hash is not None:
                    self.idempotency.pop(key_hash, None)
                if job_id in self.queued:
                    self.queued.remove(job_id)
                shutil.rmtree(directory, ignore_errors=True)
                raise

    def _run(self, job: _Job) -> None:
        with self.lock:
            if job.cancel_requested:
                return
            job.record.update({"state": "running", "started_at": _utc()})
            self._save(job)
        with self.lock:
            if job.cancel_requested:
                self._final(job, "canceled")
                return
        try:
            process = subprocess.Popen(
                (sys.executable, "-m", "vectorai_api.job_worker", str(job.directory)),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                cwd=self.root,
            )
        except OSError:
            with self.lock:
                if job.cancel_requested:
                    self._final(job, "canceled")
                else:
                    self._final(job, "failed", error=_error("JOB_START_FAILED", retryable=True))
            return
        with self.lock:
            job.process = process
            canceled = job.cancel_requested
        if canceled:
            _stop_process(process)
        timed_out = False
        try:
            process.wait(timeout=self.max_job_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            _stop_process(process)
        with self.lock:
            job.process = None
            if job.cancel_requested:
                self._final(job, "canceled")
            elif timed_out:
                self._final(job, "failed", error=_error("RESOURCE_LIMIT", retryable=True))
            else:
                try:
                    self._publish_result(job, process.returncode)
                except (OSError, ValueError, KeyError, TypeError):
                    self._final(job, "failed", error=_error("JOB_RESULT_INVALID", retryable=True))
        self._clean_staging(job)

    def _publish_result(self, job: _Job, return_code: int | None) -> None:
        result = _read_json(job.directory / "worker-result.json")
        state = result.get("state")
        if state == "failed":
            failure = result.get("error")
            if not isinstance(failure, dict):
                raise ValueError("worker failure missing typed error")
            self._final(job, "failed", error=cast(dict[str, object], failure))
            return
        if return_code != 0 or not isinstance(state, str) or state not in PUBLISHED:
            raise ValueError("worker result disagrees with process status")
        artifact_root = job.directory / "artifacts"
        if not all(
            (artifact_root / name).is_file()
            for name in ("output.svg", "preview.png", "run-manifest.json", "validation-report.json")
        ):
            raise ValueError("validated job bundle is incomplete")
        manifest = _read_json(artifact_root / "run-manifest.json")
        engine = manifest.get("engine")
        configuration = manifest.get("configuration")
        if not isinstance(engine, dict) or not isinstance(configuration, dict):
            raise ValueError("validated manifest has no engine or configuration")
        build_id = cast(dict[str, object], engine).get("build_id")
        config_hash = cast(dict[str, object], configuration).get("config_sha256")
        if (
            not isinstance(build_id, str)
            or not build_id
            or not isinstance(config_hash, str)
            or not re.fullmatch(r"[a-f0-9]{64}", config_hash)
            or manifest.get("final_status") != state
        ):
            raise ValueError("validated manifest identity or state is missing")
        palette_count = result.get("palette_count")
        region_count = result.get("region_count")
        seam_gap_rate = result.get("seam_gap_rate")
        if (
            not isinstance(palette_count, int)
            or isinstance(palette_count, bool)
            or palette_count < 1
            or not isinstance(region_count, int)
            or isinstance(region_count, bool)
            or region_count < 1
            or not isinstance(seam_gap_rate, (int, float))
            or isinstance(seam_gap_rate, bool)
            or not math.isfinite(seam_gap_rate)
            or not 0.0 <= seam_gap_rate <= 1.0
        ):
            raise ValueError("validated result metrics are invalid")
        job.record.update(
            {
                "artifacts": {
                    name: f"/v1/jobs/{job.job_id}/artifacts/{name}"
                    for name in ARTIFACTS
                    if (artifact_root / name).is_file()
                },
                "engine_build_id": build_id,
                "config_sha256": config_hash,
                "palette_count": palette_count,
                "region_count": region_count,
                "seam_gap_rate": seam_gap_rate,
            }
        )
        self._final(job, state)

    def _clean_staging(self, job: _Job) -> None:
        for candidate in job.directory.glob(".artifacts-*"):
            if candidate.is_dir() and not candidate.is_symlink():
                try:
                    shutil.rmtree(candidate)
                except OSError:
                    with self.lock:
                        job.record["cleanup_pending"] = True
                        self._save(job)

    def status(self, job_id: str) -> dict[str, object]:
        with self.lock:
            job = self.jobs.get(job_id)
            if job is not None:
                return dict(job.record)
            directory = self._directory(job_id)
            try:
                return _read_json(directory / "job-status.json")
            except (OSError, ValueError) as error:
                raise FileNotFoundError("unknown job") from error

    def cancel(self, job_id: str) -> dict[str, object]:
        with self.lock:
            job = self.jobs.get(job_id)
            if job is None:
                record = self.status(job_id)
                if record.get("state") in TERMINAL:
                    raise ValueError("job has already completed")
                raise ValueError("job is no longer owned by this process")
            if job.record["state"] in TERMINAL:
                raise ValueError("job has already completed")
            job.cancel_requested = True
            job.record["cancel_requested"] = True
            if job.record["state"] == "accepted":
                self._final(job, "canceled")
                return dict(job.record)
            self._save(job)
            process = job.process
            result = dict(job.record)
        if process is not None:
            _stop_process(process)
        return result

    def has_active(self) -> bool:
        with self.lock:
            return self.active is not None

    def can_download(self, job_id: str) -> bool:
        record = self.status(job_id)
        return record.get("state") in PUBLISHED

    def shutdown(self) -> None:
        with self.lock:
            self.closing = True
            for job_id in tuple(self.queued):
                queued_job = self.jobs.get(job_id)
                if queued_job is not None:
                    queued_job.cancel_requested = True
                    self._final(queued_job, "canceled")
            active = self.jobs.get(self.active) if self.active is not None else None
            if active is None:
                return
            active.cancel_requested = True
            process = active.process
            thread = active.thread
        if process is not None:
            _stop_process(process)
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=10.0)
