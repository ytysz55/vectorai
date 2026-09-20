from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from vectorai_engine.errors import EngineFailure
from vectorai_engine.multicolor_graph import build_multicolor_region_graph
from vectorai_engine.segmentation import SpatialSegmentation
from vectorai_engine.shared_boundary import (
    assemble_shared_boundaries,
    measure_renderer_seams,
    validate_shared_boundary_assembly,
)


def two_color_segmentation() -> SpatialSegmentation:
    labels = np.zeros((6, 10), dtype=np.int16)
    labels[:, 5:] = 1
    confidence = np.ones(labels.shape, dtype=np.float32)
    labels.setflags(write=False)
    confidence.setflags(write=False)
    return SpatialSegmentation(labels, confidence, (), 1)


def render(path: Path, *, gap: bool = False, blue: int = 255) -> None:
    image = Image.new("RGBA", (10, 6), (255, 0, 0, 255))
    for x in range(5, 10):
        for y in range(6):
            image.putpixel((x, y), (0, 0, blue, 255))
    if gap:
        for y in range(6):
            image.putpixel((5, y), (0, 0, 0, 0))
    image.save(path)


def test_shared_faces_reference_one_geometry_in_reverse() -> None:
    segmentation = two_color_segmentation()
    graph = build_multicolor_region_graph(segmentation)
    assembly = assemble_shared_boundaries(graph, segmentation)
    assert len(assembly.seam_pairs) == 1
    pair = assembly.seam_pairs[0]
    assert pair.faces == (1, 2)
    assert len(pair.canonical_edges) == 6
    assert pair.maximum_twin_error == 0.0
    assert pair.total_length == 6.0
    validate_shared_boundary_assembly(graph, assembly)


def test_renderer_seam_matrix_detects_gap_and_disagreement(tmp_path: Path) -> None:
    segmentation = two_color_segmentation()
    graph = build_multicolor_region_graph(segmentation)
    assembly = assemble_shared_boundaries(graph, segmentation)
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    render(first)
    render(second, blue=240)
    clean = measure_renderer_seams(assembly, {"resvg": first, "chromium": second})
    assert all(item.transparent_gap_rate == 0.0 for item in clean.observations)
    assert all(item.minimum_alpha == 1.0 for item in clean.observations)
    assert abs(clean.maximum_renderer_channel_delta - 15.0 / 255.0) < 1e-12

    broken = tmp_path / "broken.png"
    render(broken, gap=True)
    gap = measure_renderer_seams(assembly, {"broken": broken})
    assert gap.observations[0].transparent_gap_rate == 0.5
    assert gap.observations[0].minimum_alpha == 0.0


def test_renderer_seam_matrix_accepts_an_image_without_shared_seams(tmp_path: Path) -> None:
    labels = np.zeros((6, 10), dtype=np.int16)
    confidence = np.ones(labels.shape, dtype=np.float32)
    labels.setflags(write=False)
    confidence.setflags(write=False)
    segmentation = SpatialSegmentation(labels, confidence, (), 0)
    graph = build_multicolor_region_graph(segmentation)
    assembly = assemble_shared_boundaries(graph, segmentation)
    output = tmp_path / "solid.png"
    Image.new("RGBA", (10, 6), (0, 0, 0, 255)).save(output)

    matrix = measure_renderer_seams(assembly, {"resvg": output})

    assert matrix.observations[0].sample_count == 0
    assert matrix.observations[0].transparent_gap_rate == 0.0
    assert matrix.maximum_renderer_channel_delta == 0.0


def test_validator_rejects_missing_face_reference() -> None:
    segmentation = two_color_segmentation()
    graph = build_multicolor_region_graph(segmentation)
    assembly = assemble_shared_boundaries(graph, segmentation)
    references = list(assembly.face_references)
    references[1] = references[1][1:]
    broken = replace(assembly, face_references=tuple(references))
    with pytest.raises(EngineFailure):
        validate_shared_boundary_assembly(graph, broken)
