from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest

from vectorai_engine.profiles import OptimizationMode, load_optimizer_profiles

ROOT = Path(__file__).resolve().parents[2]
PROFILE_PATH = ROOT / "benchmark" / "configs" / "optimizer-profiles-v1.json"


def load_payload() -> dict[str, Any]:
    payload = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError("optimizer profile fixture must be an object")
    return cast(dict[str, Any], payload)


def test_four_external_profiles_load_with_stable_hashes() -> None:
    profile_set = load_optimizer_profiles(PROFILE_PATH)

    assert tuple(profile.mode for profile in profile_set.profiles) == tuple(OptimizationMode)
    assert len(profile_set.sha256) == 64
    assert len({profile.sha256 for profile in profile_set.profiles}) == 4
    assert profile_set.select("faithful").weights.fidelity == 0.55
    assert profile_set.select("minimal").weights.complexity == 0.45
    assert profile_set.select("cut_ready").limits.minimum_positive_geometry == 0.10


def test_profile_hash_uses_canonical_json_not_file_whitespace(tmp_path: Path) -> None:
    payload = load_payload()
    reformatted = tmp_path / "profiles.json"
    reformatted.write_text(json.dumps(payload, indent=7), encoding="utf-8")

    first = load_optimizer_profiles(PROFILE_PATH)
    second = load_optimizer_profiles(reformatted)

    assert second.sha256 == first.sha256
    assert tuple(profile.sha256 for profile in second.profiles) == tuple(
        profile.sha256 for profile in first.profiles
    )


def test_profile_loader_rejects_unknown_fields(tmp_path: Path) -> None:
    payload = load_payload()
    payload["unexpected"] = True
    path = tmp_path / "unknown.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="unknown"):
        load_optimizer_profiles(path)


def test_profile_loader_rejects_noncanonical_mode_order(tmp_path: Path) -> None:
    payload = load_payload()
    profiles = payload["profiles"]
    assert isinstance(profiles, list)
    profiles[0], profiles[1] = profiles[1], profiles[0]
    path = tmp_path / "order.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="exactly once in order"):
        load_optimizer_profiles(path)


def test_profile_loader_rejects_invalid_weights_and_schedule(tmp_path: Path) -> None:
    payload = load_payload()
    profile = payload["profiles"][0]
    profile["weights"]["fidelity"] = 0.7
    path = tmp_path / "weights.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="sum to one"):
        load_optimizer_profiles(path)

    payload = load_payload()
    profile = payload["profiles"][0]
    profile["limits"]["step_schedule"] = [0.5, 1.0]
    path = tmp_path / "schedule.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="strictly decreasing"):
        load_optimizer_profiles(path)
