"""Bounded read-only source-coordinate geometry for local E7 inspection."""

from __future__ import annotations

import math

from .multicolor_scene import MulticolorScene
from .shared_boundary import SharedBoundaryAssembly

MAX_NODES = 2_000
MAX_SHARED_EDGES = 4_000


def multicolor_scene_overlay(
    scene: MulticolorScene, assembly: SharedBoundaryAssembly
) -> dict[str, object]:
    """Selected-scene vertices and canonical graph evidence, never seam-cover strokes.

    Node indices are stable within a job; their coordinates may be prefit anchors rather
    than literal exported SVG commands. Shared edges are raw canonical graph segments,
    not a claim that the final simplified/optimized SVG contains each grid edge.
    """
    node_count = sum(len(cycle) for face in scene.faces for cycle in face.cycles)
    internal = tuple(segment for segment in assembly.segments if 0 not in segment.faces)
    if node_count > MAX_NODES or len(internal) > MAX_SHARED_EDGES:
        return {
            "schema_version": "1.0.0",
            "available": False,
            "reason": "OVERLAY_BUDGET_EXCEEDED",
            "nodes": [],
            "shared_edges": [],
            "faces": [],
        }
    nodes: list[dict[str, object]] = []
    faces: list[dict[str, object]] = []
    for face in scene.faces:
        if face.face_id <= 0:
            raise ValueError("overlay face IDs must be positive")
        faces.append(
            {
                "id": f"face-{face.face_id}",
                "face_id": face.face_id,
                "cycles": [[[x, y] for x, y in cycle] for cycle in face.cycles],
            }
        )
        for cycle_index, cycle in enumerate(face.cycles):
            for point_index, (x, y) in enumerate(cycle):
                if not math.isfinite(x) or not math.isfinite(y):
                    raise ValueError("overlay geometry must be finite")
                nodes.append(
                    {
                        "id": f"face-{face.face_id}-cycle-{cycle_index}-node-{point_index}",
                        "face_id": face.face_id,
                        "x": x,
                        "y": y,
                    }
                )
    shared_edges: list[dict[str, object]] = []
    for segment in internal:
        a, b = segment.faces
        if a <= 0 or b <= a:
            raise ValueError("shared edge must join two distinct positive faces")
        shared_edges.append(
            {
                "id": f"edge-{segment.canonical_edge}",
                "faces": [a, b],
                "start": [segment.start.x, segment.start.y],
                "end": [segment.end.x, segment.end.y],
            }
        )
    return {
        "schema_version": "1.0.0",
        "available": True,
        "reason": None,
        "faces": faces,
        "nodes": nodes,
        "shared_edges": shared_edges,
    }
