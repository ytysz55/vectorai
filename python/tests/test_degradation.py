from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image

from vectorai_bench.degradation import (
    DegradationRecipe,
    apply_degradation,
    default_recipes,
    generate_degraded_variants,
)
from vectorai_bench.fixtures import generate_fixture_set
from vectorai_bench.models import VariantTier


def tree_digests(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_degradation_dataset_is_byte_deterministic(tmp_path: Path) -> None:
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"
    generate_fixture_set(first_dir)
    generate_fixture_set(second_dir)
    first = generate_degraded_variants(first_dir)
    second = generate_degraded_variants(second_dir)
    assert first == second
    assert tree_digests(first_dir) == tree_digests(second_dir)


def test_default_tiers_generate_four_variants_per_family(tmp_path: Path) -> None:
    generate_fixture_set(tmp_path)
    manifest = generate_degraded_variants(tmp_path)
    assert len(manifest.cases) == len(manifest.families) * len(default_recipes())
    assert {case.variant.tier for case in manifest.cases} == set(VariantTier)
    for case in manifest.cases:
        assert case.variant.parameters["resize_kernel"] == "lanczos"
        assert case.variant.parameters["operation_colorspace"] == "srgb"


def test_noise_is_seed_controlled() -> None:
    source = Image.new("RGBA", (32, 32), (100, 120, 140, 255))
    recipe = DegradationRecipe("noise", VariantTier.T2, 32, 32, 10, noise_sigma=4.0)
    first = np.asarray(apply_degradation(source, recipe, case_seed=100))
    second = np.asarray(apply_degradation(source, recipe, case_seed=100))
    different = np.asarray(apply_degradation(source, recipe, case_seed=101))
    assert np.array_equal(first, second)
    assert not np.array_equal(first, different)


def test_hostile_recipe_changes_size_and_flattens_alpha() -> None:
    source = Image.new("RGBA", (256, 256), (20, 40, 60, 127))
    recipe = default_recipes()[-1]
    result = apply_degradation(source, recipe, case_seed=recipe.seed)
    assert result.size == (64, 64)
    assert np.asarray(result.getchannel("A")).min() == 255


def test_artifact_traversal_is_rejected(tmp_path: Path) -> None:
    generate_fixture_set(tmp_path)
    manifest_path = tmp_path / "manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["cases"][0]["raster_asset"]["artifact_ref"] = "../escape.png"
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    try:
        generate_degraded_variants(tmp_path)
    except ValueError as error:
        assert "escapes dataset root" in str(error)
    else:
        raise AssertionError("path traversal must be rejected")
