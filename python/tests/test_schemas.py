from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest
from jsonschema import Draft202012Validator  # type: ignore[import-untyped]
from jsonschema.exceptions import ValidationError  # type: ignore[import-untyped]

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_DIR = ROOT / "schemas"
SCHEMA_NAMES = (
    "engine-config",
    "run-manifest",
    "validation-report",
    "benchmark-record",
    "dataset-manifest",
    "e2-g1-report",
    "multicolor-g2-report",
    "stroke-g3-report",
    "optimizer-profiles",
    "optimizer-g4-report",
    "e6-release-report",
)


def load_json(path: Path) -> object:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def load_schema(path: Path) -> dict[str, Any]:
    payload = load_json(path)
    if not isinstance(payload, dict):
        raise TypeError(f"schema must be an object: {path}")
    return cast(dict[str, Any], payload)


@pytest.mark.parametrize("name", SCHEMA_NAMES)
def test_schema_is_valid_draft_2020_12(name: str) -> None:
    schema = load_schema(SCHEMA_DIR / f"{name}.schema.json")
    Draft202012Validator.check_schema(schema)


@pytest.mark.parametrize("name", SCHEMA_NAMES)
def test_valid_fixture_is_accepted(name: str) -> None:
    schema = load_schema(SCHEMA_DIR / f"{name}.schema.json")
    fixture = load_json(SCHEMA_DIR / "fixtures" / "valid" / f"{name}.json")
    cast(Any, Draft202012Validator(schema)).validate(fixture)


@pytest.mark.parametrize("name", SCHEMA_NAMES)
def test_invalid_fixture_is_rejected(name: str) -> None:
    schema = load_schema(SCHEMA_DIR / f"{name}.schema.json")
    fixture = load_json(SCHEMA_DIR / "fixtures" / "invalid" / f"{name}.json")
    with pytest.raises(ValidationError):
        cast(Any, Draft202012Validator(schema)).validate(fixture)
