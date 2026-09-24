from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest
from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

from vectorai_engine.observability import full_run_manifest, stage_events

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = json.loads((ROOT / "schemas/run-manifest.schema.json").read_text(encoding="utf-8"))


def test_stage_events_default_redacts_input_and_debug_is_opt_in() -> None:
    source_hash = "a" * 64
    default = stage_events(
        {"decode": 1.25, "validation": 2.5},
        fallback_code="OPTIMIZER_FALLBACK",
        source_sha256=source_hash,
    )
    entries = [json.loads(line) for line in default.splitlines()]
    assert [item["code"] for item in entries] == [
        "STAGE_STARTED",
        "STAGE_COMPLETED",
        "STAGE_STARTED",
        "STAGE_COMPLETED",
        "FALLBACK_USED",
    ]
    assert source_hash.encode() not in default
    assert b"path" not in default
    debug = stage_events({"decode": 1.25}, debug_opt_in=True, source_sha256=source_hash)
    assert source_hash.encode() in debug
    with pytest.raises(ValueError):
        stage_events({"/secret/picture.png": 1.0})
    with pytest.raises(ValueError):
        stage_events({"decode": float("nan")})
    with pytest.raises(ValueError):
        stage_events({"decode": 1.0}, fallback_code="private path /Users/name")


def test_product_manifest_is_schema_valid_and_has_hashed_artifacts(tmp_path: Path) -> None:
    event_path = tmp_path / "events.jsonl"
    event_path.write_bytes(stage_events({"decode": 1.25}))
    artifact = tmp_path / "output.svg"
    artifact.write_text("<svg/>", encoding="utf-8")
    legacy: dict[str, Any] = {
        "schema_version": "1.0.0",
        "job_id": "multicolor-a",
        "input": {"sha256": "a" * 64, "bytes": 128, "media_type": "image/png"},
        "configuration": {"primitive_tolerance": 0.75, "determinism_policy": "strict"},
        "final_status": "success",
        "artifacts": ["output.svg"],
        "warnings": ["ASSUMED_SRGB_NO_ICC", "sensitive /home/user/secret.png"],
        "total_duration_ms": 3.5,
    }
    manifest = full_run_manifest(
        legacy,
        stage_durations={"decode": 1.25},
        mode="geometric",
        event_path=event_path,
        artifact_root=tmp_path,
    )
    cast(Any, Draft202012Validator(SCHEMA)).validate(manifest)
    assert manifest["warnings"] == [
        {"code": "ASSUMED_SRGB_NO_ICC", "stage": "validation", "message": "ASSUMED_SRGB_NO_ICC"},
        {"code": "PIPELINE_WARNING", "stage": "validation", "message": "PIPELINE_WARNING"},
    ]
    assert [item["name"] for item in cast(list[dict[str, object]], manifest["artifacts"])] == [
        "output.svg",
        "events.jsonl",
    ]
    assert "/home/user/secret.png" not in json.dumps(manifest)
