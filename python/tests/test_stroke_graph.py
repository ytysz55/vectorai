from __future__ import annotations

import numpy as np

from vectorai_engine.stroke_graph import StrokeNodeKind, build_centerline_graph


def test_centerline_graph_recovers_line_t_and_x_valence() -> None:
    line = np.zeros((48, 72), dtype=np.bool_)
    line[20:27, 8:64] = True
    graph = build_centerline_graph(line)
    assert graph.component_count == 1
    assert len(graph.edges) == 1
    assert [node.kind for node in graph.nodes] == [
        StrokeNodeKind.ENDPOINT,
        StrokeNodeKind.ENDPOINT,
    ]

    tee = np.zeros((72, 72), dtype=np.bool_)
    tee[10:62, 32:39] = True
    tee[10:17, 12:60] = True
    tee_graph = build_centerline_graph(tee)
    assert sorted(node.degree for node in tee_graph.nodes if node.degree >= 3) == [3]
    assert len(tee_graph.edges) == 3

    cross = np.zeros((72, 72), dtype=np.bool_)
    cross[10:62, 32:39] = True
    cross[32:39, 10:62] = True
    cross_graph = build_centerline_graph(cross)
    assert sorted(node.degree for node in cross_graph.nodes if node.degree >= 3) == [4]
    assert len(cross_graph.edges) == 4


def test_short_spur_is_removed_and_degree_two_edges_are_merged() -> None:
    mask = np.zeros((40, 64), dtype=np.bool_)
    mask[20, 6:58] = True
    mask[18:21, 32] = True

    graph = build_centerline_graph(mask, minimum_spur_length=4.0)

    assert graph.removed_spur_count == 1
    assert len(graph.edges) == 1
    assert len(graph.nodes) == 2
    assert all(node.degree == 1 for node in graph.nodes)


def test_graph_extraction_is_deterministic() -> None:
    mask = np.zeros((40, 64), dtype=np.bool_)
    mask[17:24, 8:56] = True
    first = build_centerline_graph(mask)
    second = build_centerline_graph(mask)
    assert first.nodes == second.nodes
    assert first.edges == second.edges
    assert np.array_equal(first.skeleton, second.skeleton)
