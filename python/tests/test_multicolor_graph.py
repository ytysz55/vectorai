from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from vectorai_engine.errors import EngineFailure
from vectorai_engine.multicolor_graph import (
    build_multicolor_region_graph,
    validate_multicolor_region_graph,
)
from vectorai_engine.segmentation import SpatialSegmentation


def segmentation(labels: np.ndarray) -> SpatialSegmentation:
    typed = labels.astype(np.int16)
    confidence = np.ones(labels.shape, dtype=np.float32)
    typed.setflags(write=False)
    confidence.setflags(write=False)
    return SpatialSegmentation(typed, confidence, (), 1)


def test_adjacent_colors_share_one_canonical_boundary() -> None:
    labels = np.zeros((6, 10), dtype=np.int16)
    labels[:, 5:] = 1
    graph = build_multicolor_region_graph(segmentation(labels))
    assert len(graph.faces) == 3
    assert graph.adjacency == frozenset({(1, 2)})
    assert graph.shared_boundary_lengths[(1, 2)] == 6
    shared = [
        edge for edge in graph.half_edges if {edge.face, graph.half_edges[edge.twin].face} == {1, 2}
    ]
    assert len(shared) == 12
    for edge in shared:
        twin = graph.half_edges[edge.twin]
        assert edge.canonical_edge == twin.canonical_edge
        assert edge.origin == twin.target
        assert edge.target == twin.origin
    validate_multicolor_region_graph(graph)


def test_nested_regions_have_parent_and_hole_topology() -> None:
    labels = np.full((9, 9), -1, dtype=np.int16)
    labels[1:8, 1:8] = 0
    labels[3:6, 3:6] = 1
    graph = build_multicolor_region_graph(segmentation(labels))
    outer = graph.faces[1]
    inner = graph.faces[2]
    assert outer.palette_index == 0
    assert outer.hole_count == 1
    assert inner.palette_index == 1
    assert inner.parent_face == 1
    assert graph.adjacency == frozenset({(1, 2)})


def test_same_color_ring_keeps_explicit_hole_cycle() -> None:
    labels = np.full((9, 9), -1, dtype=np.int16)
    labels[1:8, 1:8] = 0
    labels[3:6, 3:6] = -1
    graph = build_multicolor_region_graph(segmentation(labels))
    assert len(graph.faces) == 2
    assert graph.faces[1].hole_count == 1
    assert len(graph.faces[1].boundary_cycles) == 2
    assert not graph.adjacency


def test_disconnected_same_palette_entries_are_distinct_faces() -> None:
    labels = np.full((5, 9), -1, dtype=np.int16)
    labels[1:4, 1:3] = 0
    labels[1:4, 6:8] = 0
    graph = build_multicolor_region_graph(segmentation(labels))
    assert len(graph.faces) == 3
    assert graph.faces[1].palette_index == graph.faces[2].palette_index == 0
    assert graph.faces[1].pixel_count == graph.faces[2].pixel_count == 6


def test_validator_rejects_broken_twin() -> None:
    labels = np.zeros((3, 3), dtype=np.int16)
    graph = build_multicolor_region_graph(segmentation(labels))
    edges = list(graph.half_edges)
    edges[0] = replace(edges[0], twin=0)
    broken = replace(graph, half_edges=tuple(edges))
    with pytest.raises(EngineFailure):
        validate_multicolor_region_graph(broken)
