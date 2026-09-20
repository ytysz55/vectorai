from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[2]
GENERATOR_PATH = ROOT / "tools" / "legal" / "generate_notices.py"


def load_generator() -> ModuleType:
    spec = importlib.util.spec_from_file_location("generate_notices", GENERATOR_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_inventory_is_structurally_valid_for_development() -> None:
    generator = load_generator()
    payload = generator.load_inventory(generator.DEFAULT_INVENTORY)
    assert generator.validate_inventory(payload, release=False) == []


def test_release_gate_rejects_unpinned_distributed_dependencies() -> None:
    generator = load_generator()
    payload = generator.load_inventory(generator.DEFAULT_INVENTORY)
    errors = generator.validate_inventory(payload, release=True)
    assert errors
    assert any("no pinned version" in error for error in errors)


def test_notice_index_is_deterministically_sorted() -> None:
    generator = load_generator()
    payload = generator.load_inventory(generator.DEFAULT_INVENTORY)
    first = generator.render_notice_index(payload)
    second = generator.render_notice_index(payload)
    assert first == second
    assert first.index("Adobe Illustrator") < first.index("Ceres Solver")
