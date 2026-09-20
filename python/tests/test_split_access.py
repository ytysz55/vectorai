from __future__ import annotations

from pathlib import Path

import pytest

from vectorai_bench.fixtures import generate_fixture_set
from vectorai_bench.manifest import manifest_sha256
from vectorai_bench.models import Split
from vectorai_bench.split_access import (
    LockedSplitAccessError,
    LockedSplitGrant,
    select_cases,
)


def test_development_and_validation_do_not_require_grant(tmp_path: Path) -> None:
    manifest = generate_fixture_set(tmp_path)
    cases = select_cases(manifest, frozenset({Split.DEVELOPMENT, Split.VALIDATION}))
    selected_families = {case.family_id for case in cases}
    assert "synthetic-text-like-001" not in selected_families
    assert selected_families


def test_locked_split_requires_digest_bound_grant(tmp_path: Path) -> None:
    manifest = generate_fixture_set(tmp_path)
    with pytest.raises(LockedSplitAccessError, match="requires"):
        select_cases(manifest, frozenset({Split.LOCKED_TEST}))

    wrong_grant = LockedSplitGrant("1.0.0", "review-1", "0" * 64, "blind evaluation")
    with pytest.raises(LockedSplitAccessError, match="does not match"):
        select_cases(
            manifest,
            frozenset({Split.LOCKED_TEST}),
            locked_grant=wrong_grant,
        )

    grant = LockedSplitGrant(
        "1.0.0",
        "review-1",
        manifest_sha256(manifest),
        "blind evaluation",
    )
    cases = select_cases(
        manifest,
        frozenset({Split.LOCKED_TEST}),
        locked_grant=grant,
    )
    assert {case.family_id for case in cases} == {"synthetic-text-like-001"}
