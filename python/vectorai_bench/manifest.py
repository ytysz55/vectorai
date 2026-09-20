"""Canonical dataset manifest I/O and split validation."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Iterable
from pathlib import Path

from .models import DatasetManifest, ManifestValidationError, Split


class ManifestError(ValueError):
    """Raised when a benchmark manifest is unreadable or invalid."""


def canonical_manifest_bytes(manifest: DatasetManifest) -> bytes:
    payload = manifest.model_dump(mode="json", exclude_none=True)
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return (text + "\n").encode()


def manifest_sha256(manifest: DatasetManifest) -> str:
    return hashlib.sha256(canonical_manifest_bytes(manifest)).hexdigest()


def load_manifest(path: Path) -> DatasetManifest:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return DatasetManifest.model_validate(payload)
    except (OSError, json.JSONDecodeError, ManifestValidationError) as error:
        raise ManifestError(f"cannot load dataset manifest {path}: {error}") from error


def write_manifest(path: Path, manifest: DatasetManifest) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(canonical_manifest_bytes(manifest))
    except OSError as error:
        raise ManifestError(f"cannot write dataset manifest {path}: {error}") from error


def split_summary(manifest: DatasetManifest) -> dict[Split, int]:
    counts = Counter(family.split for family in manifest.families)
    return {split: counts.get(split, 0) for split in Split}


def validate_no_family_leakage(manifests: Iterable[DatasetManifest]) -> None:
    observed: dict[str, Split] = {}
    for manifest in manifests:
        for family in manifest.families:
            previous = observed.setdefault(family.family_id, family.split)
            if previous != family.split:
                raise ManifestError(
                    f"design family {family.family_id!r} appears in both "
                    f"{previous.value!r} and {family.split.value!r}"
                )
