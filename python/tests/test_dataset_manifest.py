from __future__ import annotations

import json
from pathlib import Path

import pytest

from vectorai_bench.manifest import (
    ManifestError,
    canonical_manifest_bytes,
    load_manifest,
    manifest_sha256,
    split_summary,
    validate_no_family_leakage,
    write_manifest,
)
from vectorai_bench.models import DatasetManifest, ManifestValidationError, Split

ROOT = Path(__file__).resolve().parents[2]
VALID_FIXTURE = ROOT / "schemas" / "fixtures" / "valid" / "dataset-manifest.json"


def fixture_manifest() -> DatasetManifest:
    payload = json.loads(VALID_FIXTURE.read_text(encoding="utf-8"))
    return DatasetManifest.model_validate(payload)


def test_valid_manifest_has_stable_canonical_digest() -> None:
    manifest = fixture_manifest()
    first = canonical_manifest_bytes(manifest)
    second = canonical_manifest_bytes(manifest)
    assert first == second
    assert len(manifest_sha256(manifest)) == 64
    assert first.endswith(b"\n")


def test_manifest_round_trips_canonically(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    manifest = fixture_manifest()
    write_manifest(path, manifest)
    assert load_manifest(path) == manifest
    assert path.read_bytes() == canonical_manifest_bytes(manifest)


def test_summary_counts_families_not_variants() -> None:
    summary = split_summary(fixture_manifest())
    assert summary == {
        Split.DEVELOPMENT: 1,
        Split.VALIDATION: 0,
        Split.LOCKED_TEST: 0,
    }


def test_unknown_family_reference_is_rejected() -> None:
    payload = json.loads(VALID_FIXTURE.read_text(encoding="utf-8"))
    payload["cases"][0]["family_id"] = "missing-family"
    with pytest.raises(ManifestValidationError, match="unknown families"):
        DatasetManifest.model_validate(payload)


def test_unsorted_ids_are_rejected() -> None:
    payload = json.loads(VALID_FIXTURE.read_text(encoding="utf-8"))
    duplicate = dict(payload["cases"][0])
    duplicate["case_id"] = "aaa-first"
    payload["cases"].append(duplicate)
    with pytest.raises(ManifestValidationError, match="sorted by case_id"):
        DatasetManifest.model_validate(payload)


def test_family_leakage_across_manifests_is_rejected() -> None:
    first = fixture_manifest()
    payload = json.loads(canonical_manifest_bytes(first))
    payload["families"][0]["split"] = "validation"
    second = DatasetManifest.model_validate(payload)
    with pytest.raises(ManifestError, match="appears in both"):
        validate_no_family_leakage((first, second))
