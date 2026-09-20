"""Isolated, version-pinned benchmark baseline adapters."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from PIL import Image, UnidentifiedImageError

from .external_tools import ProbeResult, ToolIdentity, ToolStatus, file_sha256, run_command
from .metrics.editability import measure_svg_editability

MAX_RASTER_PIXELS = 16_777_216
MAX_RASTER_BYTES = 64 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class BaselinePreset:
    name: str
    arguments: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BaselineResult:
    status: ToolStatus
    baseline: str
    preset: str
    arguments: tuple[str, ...]
    identity: ToolIdentity | None
    wall_time_ms: float
    peak_rss_bytes: int | None = None
    output_sha256: str | None = None
    message: str = ""


@dataclass(frozen=True, slots=True)
class VTracerLock:
    version: str
    version_output: str
    archive_url: str
    archive_sha256: str
    executable_sha256: str
    presets: dict[str, BaselinePreset]


def load_vtracer_lock(lock_path: Path, platform_key: str) -> VTracerLock:
    try:
        payload = json.loads(lock_path.read_text(encoding="utf-8"))
        platform = payload["platforms"][platform_key]
        raw_presets = payload["presets"]
        if not isinstance(raw_presets, dict):
            raise TypeError("presets must be an object")
        presets: dict[str, BaselinePreset] = {}
        for raw_name, raw_definition in cast(dict[object, object], raw_presets).items():
            if not isinstance(raw_name, str) or not isinstance(raw_definition, dict):
                raise TypeError("preset names and definitions must be objects")
            definition = cast(dict[str, object], raw_definition)
            arguments = definition.get("arguments")
            if not isinstance(arguments, list) or not all(
                isinstance(argument, str) for argument in arguments
            ):
                raise TypeError(f"preset {raw_name!r} arguments must be strings")
            presets[raw_name] = BaselinePreset(raw_name, tuple(arguments))
        return VTracerLock(
            version=str(payload["version"]),
            version_output=str(payload["version_output"]),
            archive_url=str(platform["archive_url"]),
            archive_sha256=str(platform["archive_sha256"]),
            executable_sha256=str(platform["executable_sha256"]),
            presets=presets,
        )
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as error:
        raise ValueError(f"invalid VTracer lock {lock_path}: {error}") from error


def _resolve_command(
    name: str,
    executable: Path | None,
    command_prefix: tuple[str, ...] | None,
) -> tuple[str, ...] | None:
    if command_prefix:
        first = shutil.which(command_prefix[0]) or command_prefix[0]
        if not Path(first).is_file():
            return None
        return (str(Path(first).resolve()), *command_prefix[1:])
    if executable is not None:
        resolved = executable.resolve()
        return (str(resolved),) if resolved.is_file() else None
    discovered = shutil.which(name)
    return (str(Path(discovered).resolve()),) if discovered else None


def _probe_tool(
    name: str,
    command: tuple[str, ...] | None,
    *,
    expected_version_output: str | None,
    expected_executable_sha256: str | None,
    timeout_seconds: float,
) -> ProbeResult:
    if command is None:
        return ProbeResult(ToolStatus.UNAVAILABLE, message=f"{name} executable not found")
    executable = Path(command[0])
    executable_sha256 = file_sha256(executable)
    version_result = run_command((*command, "--version"), timeout_seconds=timeout_seconds)
    if version_result.status is not ToolStatus.SUCCESS:
        return ProbeResult(
            version_result.status,
            message=(
                version_result.stderr or version_result.stdout or f"{name} version probe failed"
            ),
        )
    output = (version_result.stdout or version_result.stderr).strip()
    version = output.splitlines()[0] if output else ""
    identity = ToolIdentity(name, str(executable), version, executable_sha256)
    if expected_version_output is not None and version != expected_version_output:
        return ProbeResult(
            ToolStatus.VERSION_MISMATCH,
            identity,
            f"expected {expected_version_output!r}, got {version!r}",
        )
    if expected_executable_sha256 is not None and executable_sha256 != expected_executable_sha256:
        return ProbeResult(
            ToolStatus.VERSION_MISMATCH,
            identity,
            f"{name} executable checksum mismatch",
        )
    return ProbeResult(ToolStatus.READY, identity)


def _validate_raster(path: Path) -> str | None:
    try:
        if path.stat().st_size > MAX_RASTER_BYTES:
            return f"raster exceeds {MAX_RASTER_BYTES} bytes"
        with Image.open(path) as image:
            if image.width * image.height > MAX_RASTER_PIXELS:
                return f"raster exceeds {MAX_RASTER_PIXELS} pixels"
            image.verify()
    except (OSError, UnidentifiedImageError) as error:
        return f"invalid raster input: {error}"
    return None


def _validate_svg(path: Path, *, allow_known_svg_10_doctype: bool = False) -> str | None:
    try:
        measure_svg_editability(path, allow_known_svg_10_doctype=allow_known_svg_10_doctype)
    except ValueError as error:
        return f"invalid SVG output: {error}"
    return None


class VTracerAdapter:
    def __init__(
        self,
        *,
        presets: dict[str, BaselinePreset],
        executable: Path | None = None,
        command_prefix: tuple[str, ...] | None = None,
        expected_version_output: str | None = None,
        expected_executable_sha256: str | None = None,
        probe_timeout_seconds: float = 5.0,
    ) -> None:
        self._command = _resolve_command("vtracer", executable, command_prefix)
        self._presets = dict(presets)
        self._expected_version = expected_version_output
        self._expected_sha256 = expected_executable_sha256
        self._probe_timeout = probe_timeout_seconds
        self._probe: ProbeResult | None = None

    def probe(self) -> ProbeResult:
        if self._probe is None:
            self._probe = _probe_tool(
                "vtracer",
                self._command,
                expected_version_output=self._expected_version,
                expected_executable_sha256=self._expected_sha256,
                timeout_seconds=self._probe_timeout,
            )
        return self._probe

    def vectorize(
        self,
        raster_path: Path,
        output_path: Path,
        *,
        preset_name: str,
        timeout_seconds: float = 30.0,
    ) -> BaselineResult:
        preset = self._presets.get(preset_name)
        if preset is None:
            return BaselineResult(
                ToolStatus.FAILED,
                "vtracer",
                preset_name,
                (),
                None,
                0.0,
                message=f"unknown VTracer preset: {preset_name}",
            )
        probe = self.probe()
        if probe.status is not ToolStatus.READY or probe.identity is None or self._command is None:
            return BaselineResult(
                probe.status,
                "vtracer",
                preset.name,
                preset.arguments,
                probe.identity,
                0.0,
                message=probe.message,
            )
        validation_error = _validate_raster(raster_path)
        if validation_error is not None:
            return BaselineResult(
                ToolStatus.FAILED,
                "vtracer",
                preset.name,
                preset.arguments,
                probe.identity,
                0.0,
                message=validation_error,
            )

        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            handle, temporary_name = tempfile.mkstemp(
                prefix=".vtracer-", suffix=".svg", dir=output_path.parent
            )
            os.close(handle)
            temporary_path = Path(temporary_name)
        except OSError as error:
            return BaselineResult(
                ToolStatus.FAILED,
                "vtracer",
                preset.name,
                preset.arguments,
                probe.identity,
                0.0,
                message=f"cannot create output: {error}",
            )

        try:
            result = run_command(
                (
                    *self._command,
                    "--input",
                    str(raster_path.resolve()),
                    "--output",
                    str(temporary_path.resolve()),
                    *preset.arguments,
                ),
                timeout_seconds=timeout_seconds,
            )
            if result.status is not ToolStatus.SUCCESS:
                return BaselineResult(
                    result.status,
                    "vtracer",
                    preset.name,
                    preset.arguments,
                    probe.identity,
                    result.wall_time_ms,
                    message=result.stderr or result.stdout,
                )
            validation_error = _validate_svg(temporary_path)
            if validation_error is not None:
                return BaselineResult(
                    ToolStatus.INVALID_OUTPUT,
                    "vtracer",
                    preset.name,
                    preset.arguments,
                    probe.identity,
                    result.wall_time_ms,
                    message=validation_error,
                )
            output_sha256 = hashlib.sha256(temporary_path.read_bytes()).hexdigest()
            temporary_path.replace(output_path)
            return BaselineResult(
                ToolStatus.SUCCESS,
                "vtracer",
                preset.name,
                preset.arguments,
                probe.identity,
                result.wall_time_ms,
                output_sha256=output_sha256,
            )
        finally:
            temporary_path.unlink(missing_ok=True)


@dataclass(frozen=True, slots=True)
class PotraceLock:
    version: str
    version_output: str
    source_archive_url: str
    source_archive_sha256: str
    executable_sha256: str | None
    presets: dict[str, BaselinePreset]


def load_potrace_lock(lock_path: Path, platform_key: str) -> PotraceLock:
    try:
        payload = json.loads(lock_path.read_text(encoding="utf-8"))
        platform = payload["platforms"][platform_key]
        raw_presets = payload["presets"]
        if not isinstance(raw_presets, dict):
            raise TypeError("presets must be an object")
        presets: dict[str, BaselinePreset] = {}
        for raw_name, raw_definition in cast(dict[object, object], raw_presets).items():
            if not isinstance(raw_name, str) or not isinstance(raw_definition, dict):
                raise TypeError("preset names and definitions must be objects")
            definition = cast(dict[str, object], raw_definition)
            arguments = definition.get("arguments")
            if not isinstance(arguments, list) or not all(
                isinstance(argument, str) for argument in arguments
            ):
                raise TypeError(f"preset {raw_name!r} arguments must be strings")
            presets[raw_name] = BaselinePreset(raw_name, tuple(arguments))
        executable_sha256 = platform.get("executable_sha256")
        if executable_sha256 is not None and not isinstance(executable_sha256, str):
            raise TypeError("executable_sha256 must be a string or null")
        return PotraceLock(
            version=str(payload["version"]),
            version_output=str(payload["version_output"]),
            source_archive_url=str(payload["source"]["archive_url"]),
            source_archive_sha256=str(payload["source"]["archive_sha256"]),
            executable_sha256=executable_sha256,
            presets=presets,
        )
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as error:
        raise ValueError(f"invalid Potrace lock {lock_path}: {error}") from error


def _validate_pbm(path: Path) -> str | None:
    try:
        if path.stat().st_size > MAX_RASTER_BYTES:
            return f"PBM exceeds {MAX_RASTER_BYTES} bytes"
        magic = path.read_bytes()[:2]
    except OSError as error:
        return f"cannot read PBM input: {error}"
    if magic not in {b"P1", b"P4"}:
        return "Potrace baseline accepts only PBM P1/P4 binary inputs"
    return None


class PotraceAdapter:
    """GPL-isolated Potrace subprocess adapter; no libpotrace linkage is permitted."""

    def __init__(
        self,
        *,
        presets: dict[str, BaselinePreset],
        executable: Path | None = None,
        command_prefix: tuple[str, ...] | None = None,
        expected_version_output: str | None = None,
        expected_executable_sha256: str | None = None,
        probe_timeout_seconds: float = 5.0,
    ) -> None:
        self._command = _resolve_command("potrace", executable, command_prefix)
        self._presets = dict(presets)
        self._expected_version = expected_version_output
        self._expected_sha256 = expected_executable_sha256
        self._probe_timeout = probe_timeout_seconds
        self._probe: ProbeResult | None = None

    def probe(self) -> ProbeResult:
        if self._probe is None:
            self._probe = _probe_tool(
                "potrace",
                self._command,
                expected_version_output=self._expected_version,
                expected_executable_sha256=self._expected_sha256,
                timeout_seconds=self._probe_timeout,
            )
        return self._probe

    def vectorize(
        self,
        pbm_path: Path,
        output_path: Path,
        *,
        preset_name: str,
        timeout_seconds: float = 30.0,
    ) -> BaselineResult:
        preset = self._presets.get(preset_name)
        if preset is None:
            return BaselineResult(
                ToolStatus.FAILED,
                "potrace",
                preset_name,
                (),
                None,
                0.0,
                message=f"unknown Potrace preset: {preset_name}",
            )
        probe = self.probe()
        if probe.status is not ToolStatus.READY or probe.identity is None or self._command is None:
            return BaselineResult(
                probe.status,
                "potrace",
                preset.name,
                preset.arguments,
                probe.identity,
                0.0,
                message=probe.message,
            )
        validation_error = _validate_pbm(pbm_path)
        if validation_error is not None:
            return BaselineResult(
                ToolStatus.FAILED,
                "potrace",
                preset.name,
                preset.arguments,
                probe.identity,
                0.0,
                message=validation_error,
            )

        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            handle, temporary_name = tempfile.mkstemp(
                prefix=".potrace-", suffix=".svg", dir=output_path.parent
            )
            os.close(handle)
            temporary_path = Path(temporary_name)
        except OSError as error:
            return BaselineResult(
                ToolStatus.FAILED,
                "potrace",
                preset.name,
                preset.arguments,
                probe.identity,
                0.0,
                message=f"cannot create output: {error}",
            )

        try:
            result = run_command(
                (
                    *self._command,
                    *preset.arguments,
                    "--output",
                    str(temporary_path.resolve()),
                    "--",
                    str(pbm_path.resolve()),
                ),
                timeout_seconds=timeout_seconds,
            )
            if result.status is not ToolStatus.SUCCESS:
                return BaselineResult(
                    result.status,
                    "potrace",
                    preset.name,
                    preset.arguments,
                    probe.identity,
                    result.wall_time_ms,
                    message=result.stderr or result.stdout,
                )
            validation_error = _validate_svg(temporary_path, allow_known_svg_10_doctype=True)
            if validation_error is not None:
                return BaselineResult(
                    ToolStatus.INVALID_OUTPUT,
                    "potrace",
                    preset.name,
                    preset.arguments,
                    probe.identity,
                    result.wall_time_ms,
                    message=validation_error,
                )
            output_sha256 = hashlib.sha256(temporary_path.read_bytes()).hexdigest()
            temporary_path.replace(output_path)
            return BaselineResult(
                ToolStatus.SUCCESS,
                "potrace",
                preset.name,
                preset.arguments,
                probe.identity,
                result.wall_time_ms,
                output_sha256=output_sha256,
            )
        finally:
            temporary_path.unlink(missing_ok=True)
