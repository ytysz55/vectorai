from __future__ import annotations

import numpy as np
import pytest

from vectorai_engine.junctions import JunctionKind, analyze_junction_hypotheses
from vectorai_engine.multicolor_graph import build_multicolor_region_graph
from vectorai_engine.segmentation import SpatialSegmentation


def segmented(labels: list[list[int]], confidence: float = 1.0) -> SpatialSegmentation:
    array = np.asarray(labels, dtype=np.int16)
    confidence_map = np.full(array.shape, confidence, dtype=np.float32)
    array.setflags(write=False)
    confidence_map.setflags(write=False)
    return SpatialSegmentation(array, confidence_map, (), 1)


def test_checkerboard_produces_two_explicit_low_confidence_alternatives() -> None:
    segmentation = segmented([[0, 1], [1, 0]])
    graph = build_multicolor_region_graph(segmentation)
    hypotheses = analyze_junction_hypotheses(graph, segmentation)
    checkerboards = [item for item in hypotheses if item.kind is JunctionKind.CHECKERBOARD]
    assert len(checkerboards) == 1
    hypothesis = checkerboards[0]
    assert len(hypothesis.alternatives) == 2
    assert hypothesis.confidence == 0.5
    assert hypothesis.requires_review
    assert {item.name for item in hypothesis.alternatives} == {
        "northwest_southeast",
        "northeast_southwest",
    }


def test_t_junction_selects_dominant_continuation() -> None:
    segmentation = segmented([[0, 0], [1, 2]], confidence=0.8)
    graph = build_multicolor_region_graph(segmentation)
    hypotheses = analyze_junction_hypotheses(graph, segmentation)
    t_junctions = [item for item in hypotheses if item.kind is JunctionKind.T_JUNCTION]
    assert len(t_junctions) == 1
    hypothesis = t_junctions[0]
    assert hypothesis.alternatives[0].name == "dominant_continues"
    assert hypothesis.alternatives[0].score > hypothesis.alternatives[1].score
    assert hypothesis.confidence == pytest.approx(0.9)
    assert not hypothesis.requires_review


def test_simple_two_region_boundary_has_no_ambiguous_junction() -> None:
    segmentation = segmented([[0, 1], [0, 1], [0, 1]])
    graph = build_multicolor_region_graph(segmentation)
    assert analyze_junction_hypotheses(graph, segmentation) == ()


def test_junction_results_are_deterministic() -> None:
    segmentation = segmented([[0, 1], [2, 3]], confidence=0.4)
    graph = build_multicolor_region_graph(segmentation)
    first = analyze_junction_hypotheses(graph, segmentation)
    second = analyze_junction_hypotheses(graph, segmentation)
    assert first == second
    assert first[0].kind is JunctionKind.MULTIWAY
    assert first[0].requires_review
