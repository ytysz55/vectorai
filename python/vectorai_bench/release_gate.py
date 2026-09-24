"""E6 release evidence: locked gates plus actual three-renderer pixel agreement."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import cast

import numpy as np
from PIL import Image

from .metrics.fidelity import compare_rgba

LOCKED_G2_CASE_IDS = frozenset(
    {f"multicolor-{count:02d}" for count in range(2, 13)}
    | {
        f"representative-synthetic-{name}-001"
        for name in ("circle", "ring", "junction", "nested", "shared-edge", "text-like")
    }
)


@dataclass(frozen=True, slots=True)
class RendererPair:
    case_id: str
    first: str
    second: str
    white_matte_rgba_rmse: float
    raw_alpha_rmse_observation: float


@dataclass(frozen=True, slots=True)
class ReleaseEvaluation:
    passed: bool
    g2_passed: bool
    g3_passed: bool
    g4_passed: bool
    complete_renderer_matrix: bool
    repeat_digests_match: bool
    maximum_renderer_rmse: float
    renderer_pair_count: int


def _read_json(path: Path) -> dict[str, object]:
    try:
        if path.stat().st_size > 16 * 1024 * 1024:
            raise ValueError("release JSON exceeds 16 MiB budget")
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ValueError(f"cannot read release report {path.name}") from error
    if not isinstance(payload, dict):
        raise ValueError(f"release report must be an object: {path.name}")
    return cast(dict[str, object], payload)


def _rgba(path: Path) -> np.ndarray:
    if path.stat().st_size > 64 * 1024 * 1024:
        raise ValueError("release renderer PNG exceeds 64 MiB budget")
    with Image.open(path) as opened:
        if opened.width * opened.height > 4_194_304:
            raise ValueError("release renderer image exceeds the pixel budget")
        opened.load()
        return np.asarray(opened.convert("RGBA"), dtype=np.uint8)


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _white_matte(rgba: np.ndarray) -> np.ndarray:
    channels = rgba.astype(np.uint16)
    alpha = channels[..., 3:4]
    white = (channels[..., :3] * alpha + 255 * (255 - alpha) + 127) // 255
    return np.concatenate((white, np.full_like(alpha, 255)), axis=2).astype(np.uint8)


def _digest(report: dict[str, object]) -> str:
    value = report.get("semantic_digest")
    if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{64}", value):
        raise ValueError("gate report has no semantic SHA-256 digest")
    return value


def _passed(report: dict[str, object]) -> bool:
    evaluation = report.get("evaluation")
    if not isinstance(evaluation, dict):
        return False
    value = cast(dict[str, object], evaluation).get("passed")
    return isinstance(value, bool) and value


def build_e6_release_report(
    g2_directory: Path,
    g3_directory: Path,
    g4_directory: Path,
    *,
    g2_repeat: Path | None = None,
    g3_repeat: Path | None = None,
    g4_repeat: Path | None = None,
    renderer_rmse_limit: float = 0.08,
) -> dict[str, object]:
    """Require all locked gates and pairwise resvg/Chromium/Inkscape evidence."""

    if not 0.0 < renderer_rmse_limit <= 0.08:
        raise ValueError("renderer RMSE threshold must be in (0, 0.08]")
    locations = (
        (g2_directory, "g2-report.json", g2_repeat),
        (g3_directory, "g3-report.json", g3_repeat),
        (g4_directory, "g4-report.json", g4_repeat),
    )
    reports = tuple(_read_json(root / filename) for root, filename, _ in locations)
    repeats = tuple(
        _read_json(repeat / filename) if repeat is not None else None
        for _, filename, repeat in locations
    )
    repeat_match = all(
        repeat is not None and _passed(repeat) and _digest(report) == _digest(repeat)
        for report, repeat in zip(reports, repeats, strict=True)
    )
    renderer_evidence = reports[0].get("renderer_evidence")
    if not isinstance(renderer_evidence, list) or not renderer_evidence:
        raise ValueError("G2 report has no renderer case evidence")
    pairs: list[RendererPair] = []
    case_ids: list[str] = []
    complete = True
    for entry in cast(list[object], renderer_evidence):
        if not isinstance(entry, dict):
            raise ValueError("G2 renderer case has no stable ID")
        case = cast(dict[str, object], entry)
        case_id = case.get("case_id")
        if not isinstance(case_id, str) or not re.fullmatch(r"[A-Za-z0-9._-]+", case_id):
            raise ValueError("G2 renderer case has no stable ID")
        case_ids.append(case_id)
        observations = case.get("observations")
        observed: set[str] = set()
        if isinstance(observations, list):
            for observation in cast(list[object], observations):
                if isinstance(observation, dict):
                    name = cast(dict[str, object], observation).get("renderer")
                    if isinstance(name, str):
                        observed.add(name)
        if observed != {"resvg", "chromium", "inkscape"}:
            complete = False
        root = g2_directory / "runs" / case_id / "engine"
        manifest = _read_json(root / "run-manifest.json")
        aux = manifest.get("auxiliary_renderers")
        statuses: dict[str, str] = {}
        if isinstance(aux, list):
            for item in cast(list[object], aux):
                if isinstance(item, dict):
                    auxiliary = cast(dict[str, object], item)
                    name, status = auxiliary.get("name"), auxiliary.get("status")
                    if isinstance(name, str) and isinstance(status, str):
                        statuses[name] = status
        if any(statuses.get(name) != "success" for name in ("chromium", "inkscape")):
            complete = False
        names = {
            "resvg": root / "preview.png",
            "chromium": root / "preview-chromium.png",
            "inkscape": root / "preview-inkscape.png",
        }
        if not all(path.is_file() for path in names.values()):
            complete = False
            continue
        artifacts = manifest.get("artifacts")
        artifact_hashes: dict[str, str] = {}
        if isinstance(artifacts, list):
            for entry in cast(list[object], artifacts):
                if isinstance(entry, dict):
                    record = cast(dict[str, object], entry)
                    name, sha256 = record.get("name"), record.get("sha256")
                    if isinstance(name, str) and isinstance(sha256, str):
                        artifact_hashes[name] = sha256
        if any(_file_digest(path) != artifact_hashes.get(path.name) for path in names.values()):
            complete = False
        rendered = {name: _rgba(path) for name, path in names.items()}
        white = {name: _white_matte(pixels) for name, pixels in rendered.items()}
        for first, second in (
            ("resvg", "chromium"),
            ("resvg", "inkscape"),
            ("chromium", "inkscape"),
        ):
            if rendered[first].shape != rendered[second].shape:
                complete = False
                continue
            score = compare_rgba(white[first], white[second]).premultiplied_rgba_rmse
            alpha_delta = (
                rendered[first][..., 3].astype(np.float64)
                - rendered[second][..., 3].astype(np.float64)
            ) / 255.0
            try:
                alpha_rmse = float(np.sqrt(np.mean(alpha_delta * alpha_delta)))
            except (TypeError, ValueError, OverflowError, FloatingPointError) as error:
                raise ValueError("cannot score renderer alpha agreement") from error
            pairs.append(RendererPair(case_id, first, second, score, alpha_rmse))
    complete = (
        complete
        and frozenset(case_ids) == LOCKED_G2_CASE_IDS
        and len(case_ids) == len(LOCKED_G2_CASE_IDS)
        and len(pairs) == 3 * len(case_ids)
    )
    maximum = max((pair.white_matte_rgba_rmse for pair in pairs), default=0.0)
    evaluation = ReleaseEvaluation(
        passed=False,
        g2_passed=_passed(reports[0]),
        g3_passed=_passed(reports[1]),
        g4_passed=_passed(reports[2]),
        complete_renderer_matrix=complete,
        repeat_digests_match=repeat_match,
        maximum_renderer_rmse=maximum,
        renderer_pair_count=len(pairs),
    )
    passed = (
        evaluation.g2_passed
        and evaluation.g3_passed
        and evaluation.g4_passed
        and evaluation.complete_renderer_matrix
        and evaluation.repeat_digests_match
        and maximum <= renderer_rmse_limit
    )
    evidence = {
        "gate_digests": {
            key: _digest(report) for key, report in zip(("g2", "g3", "g4"), reports, strict=True)
        },
        "renderer_pairs": [asdict(pair) for pair in pairs],
        "renderer_rmse_limit": renderer_rmse_limit,
        "comparison_background": "white",
        "criteria": {**asdict(evaluation), "passed": passed},
    }
    semantic_digest = hashlib.sha256(
        json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return {
        "schema_version": "1.0.0",
        "semantic_digest": semantic_digest,
        "gate_digests": evidence["gate_digests"],
        "renderer_pairs": evidence["renderer_pairs"],
        "renderer_rmse_limit": renderer_rmse_limit,
        "comparison_background": "white",
        "evaluation": {**asdict(evaluation), "passed": passed},
    }
