from __future__ import annotations

import numpy as np

from vectorai_bench.metrics import TopologyObservation, analyze_binary_mask, compare_topology


def test_exact_topology_scores_perfectly() -> None:
    observation = TopologyObservation(
        components=3,
        holes=1,
        adjacency=frozenset({(0, 1), (1, 2)}),
        junction_degrees=(3,),
    )
    metrics = compare_topology(observation, observation)
    assert metrics.exact_topology
    assert metrics.component_error == metrics.hole_error == metrics.euler_error == 0
    assert metrics.adjacency_precision == metrics.adjacency_recall == 1.0
    assert metrics.junction_degree_accuracy == 1.0


def test_topology_errors_and_graph_precision_are_explicit() -> None:
    reference = TopologyObservation(
        components=3,
        holes=1,
        adjacency=frozenset({(0, 1), (1, 2)}),
        junction_degrees=(3, 4),
    )
    predicted = TopologyObservation(
        components=2,
        holes=0,
        adjacency=frozenset({(0, 1), (0, 2)}),
        junction_degrees=(3, 3),
    )
    metrics = compare_topology(reference, predicted)
    assert not metrics.exact_topology
    assert metrics.component_error == 1
    assert metrics.hole_error == 1
    assert metrics.euler_error == 0
    assert metrics.adjacency_precision == metrics.adjacency_recall == 0.5
    assert metrics.adjacency_f1 == 0.5
    assert metrics.junction_degree_accuracy == 0.5


def test_binary_mask_component_and_hole_calibration() -> None:
    mask = np.zeros((12, 16), dtype=np.uint8)
    mask[1:8, 1:8] = 1
    mask[3:6, 3:6] = 0
    mask[8:11, 12:15] = 1
    observation = analyze_binary_mask(mask)
    assert observation.components == 2
    assert observation.holes == 1
    assert observation.euler_characteristic == 1


def test_empty_mask_has_no_components_or_holes() -> None:
    observation = analyze_binary_mask(np.zeros((8, 8), dtype=np.bool_))
    assert observation.components == 0
    assert observation.holes == 0
