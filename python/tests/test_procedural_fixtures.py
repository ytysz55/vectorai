from __future__ import annotations

import hashlib
from pathlib import Path

from PIL import Image

from vectorai_bench.fixtures import CANVAS_SIZE, generate_fixture_set
from vectorai_bench.models import Split


def tree_digests(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_fixture_generation_is_byte_deterministic(tmp_path: Path) -> None:
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"
    first = generate_fixture_set(first_dir)
    second = generate_fixture_set(second_dir)

    assert first == second
    assert tree_digests(first_dir) == tree_digests(second_dir)


def test_fixture_set_covers_required_topology_cases(tmp_path: Path) -> None:
    manifest = generate_fixture_set(tmp_path)
    tags = {tag for family in manifest.families for tag in family.tags}
    assert {"circle", "hole", "nested", "shared-boundary", "junction", "text-like"} <= tags
    assert len(manifest.families) == 7
    assert len({family.family_id for family in manifest.families}) == 7
    assert {family.split for family in manifest.families} == set(Split)
    assert sum(family.split is Split.DEVELOPMENT for family in manifest.families) == 5


def test_reference_rasters_are_rgba_and_sized(tmp_path: Path) -> None:
    manifest = generate_fixture_set(tmp_path)
    for case in manifest.cases:
        assert case.raster_asset is not None
        image_path = tmp_path / case.raster_asset.artifact_ref
        with Image.open(image_path) as image:
            assert image.mode == "RGBA"
            assert image.size == (CANVAS_SIZE, CANVAS_SIZE)


def test_turkish_text_truth_counts_disconnected_diacritic_and_ring(tmp_path: Path) -> None:
    manifest = generate_fixture_set(tmp_path)
    family = next(
        family for family in manifest.families if family.family_id == "synthetic-text-like-001"
    )
    assert family.ground_truth.topology.components == 4
    assert family.ground_truth.topology.holes == 1


def test_shared_edge_truth_is_canonical(tmp_path: Path) -> None:
    manifest = generate_fixture_set(tmp_path)
    family = next(
        family for family in manifest.families if family.family_id == "synthetic-shared-edge-001"
    )
    assert family.ground_truth.topology.adjacency == ((0, 1),)
    left, right = family.ground_truth.geometry.contours
    assert left[1] == right[0]
    assert left[2] == right[3]
