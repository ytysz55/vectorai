from __future__ import annotations

import io
import math
from dataclasses import replace
from pathlib import Path

import pytest
from PIL import Image

from vectorai_engine.decode import decode_bytes
from vectorai_engine.errors import EngineFailure
from vectorai_engine.multicolor_graph import MulticolorRegionGraph, build_multicolor_region_graph
from vectorai_engine.multicolor_scene import (
    SelectedFace,
    export_multicolor_svg,
    select_multicolor_scene,
)
from vectorai_engine.normalize import normalize_source
from vectorai_engine.palette import PaletteConfig, PaletteResult, generate_palette_hypotheses
from vectorai_engine.primitives import PrimitiveKind, recover_closed_primitives
from vectorai_engine.reliability import analyze_reliability
from vectorai_engine.segmentation import segment_multicolor
from vectorai_engine.shared_boundary import SharedBoundaryAssembly, assemble_shared_boundaries


def source() -> Image.Image:
    image = Image.new("RGB", (36, 20))
    for x in range(36):
        color = (220, 30, 30) if x < 18 else (25, 65, 220)
        for y in range(20):
            image.putpixel((x, y), color)
    return image


def scene() -> tuple[PaletteResult, MulticolorRegionGraph, SharedBoundaryAssembly]:
    buffer = io.BytesIO()
    source().save(buffer, format="PNG")
    normalized = normalize_source(decode_bytes(buffer.getvalue()))
    reliability = analyze_reliability(normalized)
    palette = generate_palette_hypotheses(
        normalized,
        reliability,
        PaletteConfig(minimum_colors=2, maximum_colors=2),
    )
    segmentation = segment_multicolor(normalized, palette.selected, reliability)
    graph = build_multicolor_region_graph(segmentation)
    assembly = assemble_shared_boundaries(graph, segmentation)
    return palette, graph, assembly


def test_scene_preserves_faces_and_records_top_k_scores(tmp_path: Path) -> None:
    palette, graph, assembly = scene()
    selected = select_multicolor_scene(graph, palette, assembly, top_k=3)
    payload, manifest = export_multicolor_svg(selected, palette, tmp_path / "output.svg")
    assert len(selected.faces) == 2
    assert selected.score.topology_penalty == 0.0
    assert len(selected.top_k_scores) == 3
    assert selected.top_k_scores[0] == selected.score
    assert payload.count("<rect ") == 2
    assert "stroke-width" not in payload
    assert 'data-face-id="1"' in payload
    assert 'data-face-id="2"' in payload
    assert manifest["face_count"] == 2
    assert manifest["palette_count"] == 2
    editability = manifest["editability"]
    assert isinstance(editability, dict)
    assert editability["path_count"] == 0
    assert editability["primitive_count"] == 2
    assert editability["node_count"] == 8


def test_isolated_curves_export_primitives_and_smoothed_paths(tmp_path: Path) -> None:
    palette, graph, assembly = scene()
    selected = select_multicolor_scene(graph, palette, assembly)
    circle = tuple(
        (
            3.0 + 3.0 * math.cos(2.0 * math.pi * index / 32.0),
            3.0 + 3.0 * math.sin(2.0 * math.pi * index / 32.0),
        )
        for index in range(32)
    )
    irregular = (
        (10.0, 0.0),
        (12.0, 0.0),
        (14.0, 1.0),
        (15.0, 3.0),
        (15.0, 6.0),
        (14.0, 8.0),
        (12.0, 9.0),
        (10.0, 8.0),
        (9.0, 6.0),
        (9.0, 3.0),
    )
    circle_candidates = recover_closed_primitives(circle, tolerance=1.0)
    irregular_candidates = recover_closed_primitives(irregular, tolerance=0.01)
    assert circle_candidates.selected.kind is PrimitiveKind.CIRCLE
    assert irregular_candidates.selected.kind is PrimitiveKind.POLYLINE
    curved = replace(
        selected,
        width=16,
        height=10,
        faces=(
            SelectedFace(
                1,
                0,
                (circle, irregular),
                (circle_candidates, irregular_candidates),
            ),
        ),
        has_shared_boundaries=False,
    )

    payload, manifest = export_multicolor_svg(curved, palette, tmp_path / "curved.svg")

    assert " A" in payload
    assert " Q" in payload
    editability = manifest["editability"]
    assert isinstance(editability, dict)
    assert editability["node_count"] < len(circle) + len(irregular)


def test_shared_boundary_scene_keeps_raw_canonical_cycles() -> None:
    palette, graph, assembly = scene()
    selected = select_multicolor_scene(graph, palette, assembly)
    cycle = (
        (0.0, 0.0),
        (1.0, 0.0),
        (2.0, 1.0),
        (2.0, 2.0),
        (1.0, 3.0),
        (0.0, 3.0),
    )
    candidates = recover_closed_primitives(cycle, tolerance=0.01)
    shared = replace(
        selected,
        width=3,
        height=4,
        faces=(SelectedFace(1, 0, (cycle,), (candidates,)),),
        has_shared_boundaries=True,
    )

    payload, _ = export_multicolor_svg(shared, palette)

    assert " L" in payload
    assert " Q" not in payload
    assert " A" not in payload
    assert 'stroke-width="2"' in payload


def test_scene_export_is_byte_deterministic() -> None:
    palette, graph, assembly = scene()
    selected = select_multicolor_scene(graph, palette, assembly)
    first, first_manifest = export_multicolor_svg(selected, palette)
    second, second_manifest = export_multicolor_svg(selected, palette)
    assert first == second
    assert first_manifest == second_manifest


def test_invalid_scene_dimensions_are_rejected() -> None:
    palette, graph, assembly = scene()
    selected = select_multicolor_scene(graph, palette, assembly)
    with pytest.raises(EngineFailure):
        export_multicolor_svg(replace(selected, width=0), palette)
