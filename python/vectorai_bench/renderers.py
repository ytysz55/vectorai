"""Pinned resvg reference-renderer adapter."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from .external_tools import (
    ProbeResult,
    ToolIdentity,
    ToolStatus,
    file_sha256,
    run_command,
)

MAX_SVG_BYTES = 16 * 1024 * 1024
MAX_RENDER_PIXELS = 16_777_216
_KNOWN_SVG_10_DOCTYPE = re.compile(
    rb'<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 20010904//EN"\s+'
    rb'"http://www\.w3\.org/TR/2001/REC-SVG-20010904/DTD/svg10\.dtd">'
)


@dataclass(frozen=True, slots=True)
class ResvgRelease:
    version: str
    version_output: str
    archive_url: str
    archive_sha256: str
    executable_sha256: str


@dataclass(frozen=True, slots=True)
class RenderResult:
    status: ToolStatus
    identity: ToolIdentity | None
    wall_time_ms: float
    output_sha256: str | None = None
    message: str = ""


def load_resvg_release(lock_path: Path, platform_key: str) -> ResvgRelease:
    try:
        payload = json.loads(lock_path.read_text(encoding="utf-8"))
        platform = payload["platforms"][platform_key]
        return ResvgRelease(
            version=str(payload["version"]),
            version_output=str(payload["version_output"]),
            archive_url=str(platform["archive_url"]),
            archive_sha256=str(platform["archive_sha256"]),
            executable_sha256=str(platform["executable_sha256"]),
        )
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as error:
        raise ValueError(f"invalid resvg lock {lock_path}: {error}") from error


def _resolve_command(
    executable: Path | None, command_prefix: tuple[str, ...] | None
) -> tuple[str, ...] | None:
    if command_prefix:
        first = shutil.which(command_prefix[0]) or command_prefix[0]
        if not Path(first).is_file():
            return None
        return (str(Path(first).resolve()), *command_prefix[1:])
    if executable is not None:
        resolved = executable.resolve()
        return (str(resolved),) if resolved.is_file() else None
    discovered = shutil.which("resvg")
    return (str(Path(discovered).resolve()),) if discovered else None


def _validate_svg(svg_path: Path, *, allow_known_svg_10_doctype: bool = False) -> str | None:
    try:
        if svg_path.stat().st_size > MAX_SVG_BYTES:
            return f"SVG exceeds {MAX_SVG_BYTES} bytes"
        payload = svg_path.read_bytes()
    except OSError as error:
        return f"cannot read SVG: {error}"
    upper = payload.upper()
    external_reference = re.search(
        rb"(?:href|src)\s*=\s*[\"']\s*(?:https?|file):", payload, re.IGNORECASE
    )
    if b"<!ENTITY" in upper or external_reference:
        return "external resources and XML entities are forbidden"
    if b"<!DOCTYPE" in upper and (
        not allow_known_svg_10_doctype or _KNOWN_SVG_10_DOCTYPE.search(payload) is None
    ):
        return "unknown XML document type is forbidden"
    return None


class ResvgAdapter:
    def __init__(
        self,
        *,
        executable: Path | None = None,
        command_prefix: tuple[str, ...] | None = None,
        expected_version_output: str | None = None,
        expected_executable_sha256: str | None = None,
        probe_timeout_seconds: float = 5.0,
    ) -> None:
        self._command = _resolve_command(executable, command_prefix)
        self._expected_version = expected_version_output
        self._expected_sha256 = expected_executable_sha256
        self._probe_timeout = probe_timeout_seconds
        self._probe: ProbeResult | None = None

    def probe(self) -> ProbeResult:
        if self._probe is not None:
            return self._probe
        if self._command is None:
            self._probe = ProbeResult(ToolStatus.UNAVAILABLE, message="resvg executable not found")
            return self._probe

        executable = Path(self._command[0])
        executable_sha256 = file_sha256(executable)
        version_result = run_command(
            (*self._command, "--version"), timeout_seconds=self._probe_timeout
        )
        if version_result.status is not ToolStatus.SUCCESS:
            self._probe = ProbeResult(
                version_result.status,
                message=version_result.stderr or "resvg version probe failed",
            )
            return self._probe

        version = (version_result.stdout or version_result.stderr).strip().splitlines()[0]
        identity = ToolIdentity(
            name="resvg",
            executable=str(executable),
            version=version,
            executable_sha256=executable_sha256,
        )
        if self._expected_version is not None and version != self._expected_version:
            self._probe = ProbeResult(
                ToolStatus.VERSION_MISMATCH,
                identity=identity,
                message=f"expected {self._expected_version!r}, got {version!r}",
            )
        elif self._expected_sha256 is not None and executable_sha256 != self._expected_sha256:
            self._probe = ProbeResult(
                ToolStatus.VERSION_MISMATCH,
                identity=identity,
                message="resvg executable checksum mismatch",
            )
        else:
            self._probe = ProbeResult(ToolStatus.READY, identity=identity)
        return self._probe

    def render(
        self,
        svg_path: Path,
        output_path: Path,
        *,
        width: int,
        height: int,
        timeout_seconds: float = 15.0,
        allow_known_svg_10_doctype: bool = False,
    ) -> RenderResult:
        probe = self.probe()
        if probe.status is not ToolStatus.READY or probe.identity is None or self._command is None:
            return RenderResult(probe.status, probe.identity, 0.0, message=probe.message)
        if width < 1 or height < 1 or width * height > MAX_RENDER_PIXELS:
            return RenderResult(
                ToolStatus.FAILED,
                probe.identity,
                0.0,
                message="render dimensions are out of range",
            )
        validation_error = _validate_svg(
            svg_path,
            allow_known_svg_10_doctype=allow_known_svg_10_doctype,
        )
        if validation_error is not None:
            return RenderResult(
                ToolStatus.FAILED,
                probe.identity,
                0.0,
                message=validation_error,
            )

        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            handle, temporary_name = tempfile.mkstemp(
                prefix=".resvg-", suffix=".png", dir=output_path.parent
            )
            os.close(handle)
            temporary_path = Path(temporary_name)
        except OSError as error:
            return RenderResult(
                ToolStatus.FAILED, probe.identity, 0.0, message=f"cannot create output: {error}"
            )

        try:
            result = run_command(
                (
                    *self._command,
                    "--width",
                    str(width),
                    "--height",
                    str(height),
                    str(svg_path.resolve()),
                    str(temporary_path.resolve()),
                ),
                timeout_seconds=timeout_seconds,
            )
            if result.status is not ToolStatus.SUCCESS:
                return RenderResult(
                    result.status,
                    probe.identity,
                    result.wall_time_ms,
                    message=result.stderr or result.stdout,
                )
            try:
                with Image.open(temporary_path) as image:
                    image.load()
                    if image.format != "PNG" or image.size != (width, height):
                        raise ValueError("renderer returned unexpected PNG dimensions")
            except (OSError, UnidentifiedImageError, ValueError) as error:
                return RenderResult(
                    ToolStatus.INVALID_OUTPUT,
                    probe.identity,
                    result.wall_time_ms,
                    message=str(error),
                )
            output_sha256 = hashlib.sha256(temporary_path.read_bytes()).hexdigest()
            temporary_path.replace(output_path)
            return RenderResult(
                ToolStatus.SUCCESS,
                probe.identity,
                result.wall_time_ms,
                output_sha256=output_sha256,
            )
        finally:
            temporary_path.unlink(missing_ok=True)
