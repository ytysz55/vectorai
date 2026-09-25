from __future__ import annotations

from dataclasses import replace
from typing import Any, cast

import pytest
from python.tests.test_multicolor_scene import scene

from vectorai_engine.multicolor_scene import select_multicolor_scene
from vectorai_engine.scene_overlay import MAX_NODES, multicolor_scene_overlay


def test_inspection_overlay_has_stable_face_node_and_canonical_edge_ids() -> None:
    palette, graph, assembly = scene()
    selected = select_multicolor_scene(graph, palette, assembly)
    overlay = multicolor_scene_overlay(selected, assembly)
    assert overlay == multicolor_scene_overlay(selected, assembly)
    assert overlay["available"] is True
    faces = cast(list[dict[str, Any]], overlay["faces"])
    nodes = cast(list[dict[str, Any]], overlay["nodes"])
    edges = cast(list[dict[str, Any]], overlay["shared_edges"])
    assert [face["id"] for face in faces] == [f"face-{face.face_id}" for face in selected.faces]
    assert all(node["id"].startswith(f"face-{node['face_id']}-cycle-") for node in nodes)
    internal = [segment for segment in assembly.segments if 0 not in segment.faces]
    assert len(edges) == len(internal)
    assert [edge["id"] for edge in edges] == [
        f"edge-{segment.canonical_edge}" for segment in internal
    ]
    for edge, segment in zip(edges, internal, strict=True):
        assert edge["faces"] == list(segment.faces)
        assert edge["start"] == [segment.start.x, segment.start.y]
        assert edge["end"] == [segment.end.x, segment.end.y]


def test_inspection_overlay_budget_never_changes_scene_validity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    palette, graph, assembly = scene()
    selected = select_multicolor_scene(graph, palette, assembly)
    assert MAX_NODES >= 1
    monkeypatch.setattr("vectorai_engine.scene_overlay.MAX_NODES", 1)
    overlay = multicolor_scene_overlay(selected, assembly)
    assert overlay == {
        "schema_version": "1.0.0",
        "available": False,
        "reason": "OVERLAY_BUDGET_EXCEEDED",
        "nodes": [],
        "shared_edges": [],
        "faces": [],
    }
    assert selected == replace(selected)
