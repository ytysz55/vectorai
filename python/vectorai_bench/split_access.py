"""Locked-test split intent gate and family-safe case selection."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .manifest import manifest_sha256
from .models import BenchmarkCase, DatasetManifest, Split


class LockedSplitAccessError(PermissionError):
    """Raised when locked-test cases are requested without an explicit grant."""


@dataclass(frozen=True, slots=True)
class LockedSplitGrant:
    schema_version: str
    grant_id: str
    dataset_sha256: str
    purpose: str

    def __post_init__(self) -> None:
        if self.schema_version != "1.0.0":
            raise LockedSplitAccessError("unsupported locked split grant version")
        if not self.grant_id or not self.purpose:
            raise LockedSplitAccessError("grant_id and purpose are required")
        if len(self.dataset_sha256) != 64:
            raise LockedSplitAccessError("grant dataset_sha256 must be 64 characters")


def load_locked_split_grant(path: Path) -> LockedSplitGrant:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise TypeError("grant must be an object")
        return LockedSplitGrant(
            schema_version=str(payload["schema_version"]),
            grant_id=str(payload["grant_id"]),
            dataset_sha256=str(payload["dataset_sha256"]),
            purpose=str(payload["purpose"]),
        )
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as error:
        raise LockedSplitAccessError(f"cannot load locked split grant {path}: {error}") from error


def select_cases(
    manifest: DatasetManifest,
    splits: frozenset[Split],
    *,
    locked_grant: LockedSplitGrant | None = None,
) -> tuple[BenchmarkCase, ...]:
    if not splits:
        return ()
    if Split.LOCKED_TEST in splits:
        if locked_grant is None:
            raise LockedSplitAccessError(
                "locked_test requires an out-of-repository LockedSplitGrant"
            )
        expected_digest = manifest_sha256(manifest)
        if locked_grant.dataset_sha256 != expected_digest:
            raise LockedSplitAccessError("locked split grant does not match dataset digest")

    family_splits = {family.family_id: family.split for family in manifest.families}
    return tuple(case for case in manifest.cases if family_splits[case.family_id] in splits)
