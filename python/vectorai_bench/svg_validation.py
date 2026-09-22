"""Cross-renderer SVG validation for generated engine artifacts."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import numpy as np
from PIL import Image, UnidentifiedImageError

from .external_tools import ProbeResult, ToolIdentity, ToolStatus, file_sha256, run_command
from .metrics.fidelity import compare_rgba
from .renderers import RenderResult, ResvgAdapter


class ValidationStatus(StrEnum):
    PASSED = "passed"
    NEEDS_REVIEW = "needs_review"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class RendererCheck:
    name: str
    status: ToolStatus
    output_sha256: str | None
    premultiplied_rgba_rmse: float | None
    message: str = ""


@dataclass(frozen=True, slots=True)
class SvgValidationResult:
    status: ValidationStatus
    checks: tuple[RendererCheck, ...]


class _AuxiliaryRenderer(ABC):
    name: str

    def __init__(
        self,
        *,
        command_prefix: tuple[str, ...] | None,
        expected_version: str | None,
        timeout_seconds: float,
    ) -> None:
        self._command = self._resolve(command_prefix)
        self._expected_version = expected_version
        self._timeout_seconds = timeout_seconds
        self._probe: ProbeResult | None = None

    def _resolve(self, command_prefix: tuple[str, ...] | None) -> tuple[str, ...] | None:
        if command_prefix:
            first = shutil.which(command_prefix[0]) or command_prefix[0]
            return (
                (str(Path(first).resolve()), *command_prefix[1:]) if Path(first).is_file() else None
            )
        for candidate in self.default_commands():
            discovered = shutil.which(candidate)
            if discovered:
                return (str(Path(discovered).resolve()),)
        return None

    @abstractmethod
    def default_commands(self) -> tuple[str, ...]:
        """Return executable names in discovery order."""
        return ()

    @abstractmethod
    def render_arguments(
        self, svg_path: Path, output_path: Path, width: int, height: int
    ) -> tuple[str, ...]:
        """Build renderer-specific safe command arguments."""
        return ()

    def probe(self) -> ProbeResult:
        if self._probe is not None:
            return self._probe
        if self._command is None:
            self._probe = ProbeResult(
                ToolStatus.UNAVAILABLE, message=f"{self.name} executable not found"
            )
            return self._probe
        result = run_command((*self._command, "--version"), timeout_seconds=5.0)
        if result.status is not ToolStatus.SUCCESS:
            self._probe = ProbeResult(result.status, message=result.stderr or result.stdout)
            return self._probe
        version = (result.stdout or result.stderr).strip().splitlines()[0]
        identity = ToolIdentity(
            name=self.name,
            executable=self._command[0],
            version=version,
            executable_sha256=file_sha256(Path(self._command[0])),
        )
        if self._expected_version is not None and version != self._expected_version:
            self._probe = ProbeResult(
                ToolStatus.VERSION_MISMATCH,
                identity=identity,
                message=f"expected {self._expected_version!r}, got {version!r}",
            )
        else:
            self._probe = ProbeResult(ToolStatus.READY, identity=identity)
        return self._probe

    def render(self, svg_path: Path, output_path: Path, *, width: int, height: int) -> RenderResult:
        probe = self.probe()
        if probe.status is not ToolStatus.READY or probe.identity is None or self._command is None:
            return RenderResult(probe.status, probe.identity, 0.0, message=probe.message)
        if width < 1 or height < 1 or width * height > 16_777_216:
            return RenderResult(
                ToolStatus.FAILED,
                probe.identity,
                0.0,
                message="render dimensions are out of range",
            )
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.unlink(missing_ok=True)
        except OSError as error:
            return RenderResult(ToolStatus.FAILED, probe.identity, 0.0, message=str(error))
        result = run_command(
            (*self._command, *self.render_arguments(svg_path, output_path, width, height)),
            timeout_seconds=self._timeout_seconds,
        )
        if result.status is not ToolStatus.SUCCESS:
            return RenderResult(
                result.status,
                probe.identity,
                result.wall_time_ms,
                message=result.stderr or result.stdout,
            )
        try:
            with Image.open(output_path) as image:
                image.load()
                if image.format != "PNG" or image.size != (width, height):
                    raise ValueError("renderer returned unexpected PNG dimensions")
            digest = hashlib.sha256(output_path.read_bytes()).hexdigest()
        except (OSError, UnidentifiedImageError, ValueError) as error:
            return RenderResult(
                ToolStatus.INVALID_OUTPUT,
                probe.identity,
                result.wall_time_ms,
                message=str(error),
            )
        return RenderResult(
            ToolStatus.SUCCESS,
            probe.identity,
            result.wall_time_ms,
            output_sha256=digest,
        )


class InkscapeAdapter(_AuxiliaryRenderer):
    name = "inkscape"

    def __init__(
        self,
        *,
        command_prefix: tuple[str, ...] | None = None,
        expected_version: str | None = None,
        timeout_seconds: float = 20.0,
    ) -> None:
        super().__init__(
            command_prefix=command_prefix,
            expected_version=expected_version,
            timeout_seconds=timeout_seconds,
        )

    def default_commands(self) -> tuple[str, ...]:
        return ("inkscape",)

    def render_arguments(
        self, svg_path: Path, output_path: Path, width: int, height: int
    ) -> tuple[str, ...]:
        return (
            str(svg_path.resolve()),
            "--export-type=png",
            f"--export-filename={output_path.resolve()}",
            f"--export-width={width}",
            f"--export-height={height}",
        )


class ChromiumAdapter(_AuxiliaryRenderer):
    name = "chromium"

    def __init__(
        self,
        *,
        command_prefix: tuple[str, ...] | None = None,
        expected_version: str | None = None,
        timeout_seconds: float = 20.0,
    ) -> None:
        super().__init__(
            command_prefix=command_prefix,
            expected_version=expected_version,
            timeout_seconds=timeout_seconds,
        )

    def default_commands(self) -> tuple[str, ...]:
        return ("chromium", "chromium-browser", "google-chrome", "chrome")

    def probe(self) -> ProbeResult:
        if os.name != "nt" or self._command is None:
            return super().probe()
        if self._probe is not None:
            return self._probe
        executable = Path(self._command[0])
        try:
            versions = sorted(
                (
                    child.name
                    for child in executable.parent.iterdir()
                    if child.is_dir() and re.fullmatch(r"\d+(?:\.\d+){3}", child.name)
                ),
                key=lambda value: tuple(int(part) for part in value.split(".")),
            )
        except OSError:
            versions = []
        if not versions:
            return super().probe()
        version = f"Chromium {versions[-1]}"
        identity = ToolIdentity(
            name=self.name,
            executable=str(executable),
            version=version,
            executable_sha256=file_sha256(executable),
        )
        if self._expected_version is not None and version != self._expected_version:
            self._probe = ProbeResult(
                ToolStatus.VERSION_MISMATCH,
                identity=identity,
                message=f"expected {self._expected_version!r}, got {version!r}",
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
    ) -> RenderResult:
        try:
            return super().render(svg_path, output_path, width=width, height=height)
        finally:
            shutil.rmtree(output_path.parent / ".chromium-profile", ignore_errors=True)

    def render_arguments(
        self, svg_path: Path, output_path: Path, width: int, height: int
    ) -> tuple[str, ...]:
        return (
            "--headless=new",
            "--disable-gpu",
            "--hide-scrollbars",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-background-networking",
            "--disable-component-update",
            "--disable-sync",
            "--run-all-compositor-stages-before-draw",
            f"--user-data-dir={(output_path.parent / '.chromium-profile').resolve()}",
            f"--screenshot={output_path.resolve()}",
            f"--window-size={width},{height}",
            svg_path.resolve().as_uri(),
        )


def _rgba(path: Path) -> np.ndarray:
    with Image.open(path) as image:
        return np.asarray(image.convert("RGBA"), dtype=np.uint8)


def validate_svg_renderers(
    svg_path: Path,
    output_directory: Path,
    *,
    width: int,
    height: int,
    resvg: ResvgAdapter,
    inkscape: InkscapeAdapter | None = None,
    chromium: ChromiumAdapter | None = None,
    disagreement_rmse: float = 0.02,
    require_auxiliary: bool = False,
) -> SvgValidationResult:
    if not 0.0 <= disagreement_rmse <= 1.0:
        raise ValueError("disagreement_rmse must be in [0, 1]")
    output_directory.mkdir(parents=True, exist_ok=True)
    reference_path = output_directory / "resvg.png"
    reference = resvg.render(svg_path, reference_path, width=width, height=height)
    checks = [
        RendererCheck("resvg", reference.status, reference.output_sha256, None, reference.message)
    ]
    if reference.status is not ToolStatus.SUCCESS:
        return SvgValidationResult(ValidationStatus.FAILED, tuple(checks))

    reference_rgba = _rgba(reference_path)
    status = ValidationStatus.PASSED
    for adapter in (inkscape, chromium):
        if adapter is None:
            continue
        output_path = output_directory / f"{adapter.name}.png"
        rendered = adapter.render(svg_path, output_path, width=width, height=height)
        rmse: float | None = None
        message = rendered.message
        if rendered.status is ToolStatus.SUCCESS:
            metrics = compare_rgba(reference_rgba, _rgba(output_path))
            rmse = metrics.premultiplied_rgba_rmse
            if rmse > disagreement_rmse:
                status = ValidationStatus.NEEDS_REVIEW
                message = f"renderer disagreement {rmse:.6f} exceeds {disagreement_rmse:.6f}"
        elif rendered.status in {ToolStatus.UNAVAILABLE, ToolStatus.VERSION_MISMATCH}:
            status = ValidationStatus.FAILED if require_auxiliary else ValidationStatus.NEEDS_REVIEW
        else:
            status = ValidationStatus.FAILED
        checks.append(
            RendererCheck(
                adapter.name,
                rendered.status,
                rendered.output_sha256,
                rmse,
                message,
            )
        )
    if require_auxiliary and (inkscape is None or chromium is None):
        status = ValidationStatus.FAILED
    return SvgValidationResult(status, tuple(checks))
