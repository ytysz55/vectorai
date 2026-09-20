"""Safe, observable subprocess primitives for benchmark-only external tools."""

from __future__ import annotations

import hashlib
import os
import subprocess
import time
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

MAX_CAPTURE_CHARS = 16_384


class ToolStatus(StrEnum):
    READY = "ready"
    SUCCESS = "success"
    UNAVAILABLE = "unavailable"
    VERSION_MISMATCH = "version_mismatch"
    FAILED = "failed"
    TIMEOUT = "timeout"
    INVALID_OUTPUT = "invalid_output"


@dataclass(frozen=True, slots=True)
class ToolIdentity:
    name: str
    executable: str
    version: str
    executable_sha256: str


@dataclass(frozen=True, slots=True)
class ProbeResult:
    status: ToolStatus
    identity: ToolIdentity | None = None
    message: str = ""


@dataclass(frozen=True, slots=True)
class CommandResult:
    status: ToolStatus
    return_code: int | None
    wall_time_ms: float
    stdout: str
    stderr: str


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
    except OSError as error:
        raise ValueError(f"cannot hash executable {path}: {error}") from error
    return digest.hexdigest()


def sanitized_environment() -> dict[str, str]:
    allowed = ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "HOME")
    environment = {key: os.environ[key] for key in allowed if key in os.environ}
    environment.update({"LANG": "C", "LC_ALL": "C", "TZ": "UTC"})
    return environment


def run_command(command: tuple[str, ...], *, timeout_seconds: float) -> CommandResult:
    if not command or timeout_seconds <= 0.0:
        raise ValueError("command and positive timeout are required")
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            command,
            check=False,
            shell=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=sanitized_environment(),
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as error:
        elapsed = (time.perf_counter() - started) * 1000.0
        stdout = (
            error.stdout.decode(errors="replace")
            if isinstance(error.stdout, bytes)
            else error.stdout
        )
        stderr = (
            error.stderr.decode(errors="replace")
            if isinstance(error.stderr, bytes)
            else error.stderr
        )
        return CommandResult(
            status=ToolStatus.TIMEOUT,
            return_code=None,
            wall_time_ms=elapsed,
            stdout=(stdout or "")[-MAX_CAPTURE_CHARS:],
            stderr=(stderr or "")[-MAX_CAPTURE_CHARS:],
        )
    except OSError as error:
        elapsed = (time.perf_counter() - started) * 1000.0
        return CommandResult(
            status=ToolStatus.UNAVAILABLE,
            return_code=None,
            wall_time_ms=elapsed,
            stdout="",
            stderr=str(error)[-MAX_CAPTURE_CHARS:],
        )

    elapsed = (time.perf_counter() - started) * 1000.0
    status = ToolStatus.SUCCESS if completed.returncode == 0 else ToolStatus.FAILED
    return CommandResult(
        status=status,
        return_code=completed.returncode,
        wall_time_ms=elapsed,
        stdout=completed.stdout[-MAX_CAPTURE_CHARS:],
        stderr=completed.stderr[-MAX_CAPTURE_CHARS:],
    )
