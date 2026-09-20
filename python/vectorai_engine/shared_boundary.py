"""Canonical shared-boundary assembly and renderer seam measurements."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from numpy.typing import NDArray
from PIL import Image

from .errors import EngineError, EngineFailure, ErrorCode, Stage
from .junctions import JunctionHypothesis
from .multicolor_graph import GridPoint, MulticolorRegionGraph
from .segmentation import SpatialSegmentation


@dataclass(frozen=True, slots=True)
class CanonicalBoundarySegment:
    canonical_edge: int
    start: GridPoint
    end: GridPoint
    faces: tuple[int, int]
    confidence: float
    junction_endpoint: bool


@dataclass(frozen=True, slots=True)
class FaceBoundaryReference:
    face_id: int
    half_edge_id: int
    canonical_edge: int
    reversed: bool


@dataclass(frozen=True, slots=True)
class SeamPair:
    faces: tuple[int, int]
    canonical_edges: tuple[int, ...]
    total_length: float
    maximum_twin_error: float


@dataclass(frozen=True, slots=True)
class SharedBoundaryAssembly:
    segments: tuple[CanonicalBoundarySegment, ...]
    face_references: tuple[tuple[FaceBoundaryReference, ...], ...]
    seam_pairs: tuple[SeamPair, ...]


@dataclass(frozen=True, slots=True)
class RendererSeamObservation:
    renderer: str
    sample_count: int
    transparent_gap_rate: float
    minimum_alpha: float


@dataclass(frozen=True, slots=True)
class RendererSeamMatrix:
    observations: tuple[RendererSeamObservation, ...]
    maximum_renderer_channel_delta: float


def _failure(message: str) -> EngineFailure:
    return EngineFailure(EngineError(ErrorCode.NON_MANIFOLD_GRAPH, Stage.BOUNDARY, message))


def _segment_confidence(
    segmentation: SpatialSegmentation, start: GridPoint, end: GridPoint
) -> float:
    samples: list[float] = []
    if start.x == end.x:
        x = start.x
        y = min(start.y, end.y)
        candidates = ((x - 1, y), (x, y))
    else:
        x = min(start.x, end.x)
        y = start.y
        candidates = ((x, y - 1), (x, y))
    for sample_x, sample_y in candidates:
        if (
            0 <= sample_x < segmentation.labels.shape[1]
            and 0 <= sample_y < segmentation.labels.shape[0]
        ):
            try:
                samples.append(float(segmentation.confidence[sample_y, sample_x]))
            except (TypeError, ValueError, OverflowError, IndexError):
                continue
    return min(samples) if samples else 0.0


def assemble_shared_boundaries(
    graph: MulticolorRegionGraph,
    segmentation: SpatialSegmentation,
    junctions: tuple[JunctionHypothesis, ...] = (),
) -> SharedBoundaryAssembly:
    if segmentation.labels.shape != graph.region_labels.shape:
        raise _failure("segmentation and graph dimensions do not match")
    junction_vertices = {item.vertex_id for item in junctions}
    segments: list[CanonicalBoundarySegment] = []
    references: list[list[FaceBoundaryReference]] = [[] for _ in range(len(graph.faces))]
    pair_edges: dict[tuple[int, int], list[int]] = {}
    for canonical_edge in range(graph.canonical_edge_count):
        twins = [edge for edge in graph.half_edges if edge.canonical_edge == canonical_edge]
        if len(twins) != 2:
            raise _failure("canonical boundary does not have exactly two twins")
        faces = (min(twins[0].face, twins[1].face), max(twins[0].face, twins[1].face))
        primary = twins[0] if twins[0].face == faces[0] else twins[1]
        start = graph.vertices[primary.origin].position
        end = graph.vertices[primary.target].position
        segment = CanonicalBoundarySegment(
            canonical_edge=canonical_edge,
            start=start,
            end=end,
            faces=faces,
            confidence=_segment_confidence(segmentation, start, end),
            junction_endpoint=(
                primary.origin in junction_vertices or primary.target in junction_vertices
            ),
        )
        segments.append(segment)
        for edge in twins:
            references[edge.face].append(
                FaceBoundaryReference(
                    face_id=edge.face,
                    half_edge_id=edge.half_edge_id,
                    canonical_edge=canonical_edge,
                    reversed=(edge.origin != primary.origin),
                )
            )
        if faces[0] != 0 and faces[1] != 0:
            pair_edges.setdefault(faces, []).append(canonical_edge)

    seam_pairs = tuple(
        SeamPair(
            faces=faces,
            canonical_edges=tuple(sorted(edge_ids)),
            total_length=len(edge_ids),
            maximum_twin_error=0.0,
        )
        for faces, edge_ids in sorted(pair_edges.items())
    )
    assembly = SharedBoundaryAssembly(
        segments=tuple(segments),
        face_references=tuple(
            tuple(sorted(items, key=lambda item: item.half_edge_id)) for items in references
        ),
        seam_pairs=seam_pairs,
    )
    validate_shared_boundary_assembly(graph, assembly)
    return assembly


def validate_shared_boundary_assembly(
    graph: MulticolorRegionGraph, assembly: SharedBoundaryAssembly
) -> None:
    if len(assembly.segments) != graph.canonical_edge_count:
        raise _failure("shared-boundary segment count differs from graph")
    reference_counts = [0] * graph.canonical_edge_count
    orientation_counts: list[set[bool]] = [set() for _ in range(graph.canonical_edge_count)]
    for face_id, references in enumerate(assembly.face_references):
        for reference in references:
            if (
                reference.face_id != face_id
                or reference.canonical_edge >= graph.canonical_edge_count
                or reference.half_edge_id >= len(graph.half_edges)
            ):
                raise _failure("face boundary reference is out of range")
            edge = graph.half_edges[reference.half_edge_id]
            if edge.face != face_id or edge.canonical_edge != reference.canonical_edge:
                raise _failure("face boundary reference disagrees with graph")
            reference_counts[reference.canonical_edge] += 1
            orientation_counts[reference.canonical_edge].add(reference.reversed)
    if any(count != 2 for count in reference_counts):
        raise _failure("canonical geometry is not referenced exactly twice")
    if any(orientations != {False, True} for orientations in orientation_counts):
        raise _failure("canonical geometry is not shared in opposite orientations")
    for index, segment in enumerate(assembly.segments):
        if segment.canonical_edge != index or segment.start == segment.end:
            raise _failure("canonical segment identifiers or geometry are invalid")


def _seam_sample_coordinates(
    assembly: SharedBoundaryAssembly,
) -> tuple[tuple[int, int], ...]:
    coordinates: set[tuple[int, int]] = set()
    internal_edges = {edge for pair in assembly.seam_pairs for edge in pair.canonical_edges}
    for edge_id in internal_edges:
        segment = assembly.segments[edge_id]
        if segment.start.x == segment.end.x:
            x = segment.start.x
            y = min(segment.start.y, segment.end.y)
            coordinates.add((x - 1, y))
            coordinates.add((x, y))
        else:
            x = min(segment.start.x, segment.end.x)
            y = segment.start.y
            coordinates.add((x, y - 1))
            coordinates.add((x, y))
    return tuple(sorted(coordinates))


def measure_renderer_seams(
    assembly: SharedBoundaryAssembly,
    renderer_outputs: dict[str, Path],
) -> RendererSeamMatrix:
    if not renderer_outputs:
        raise ValueError("at least one renderer output is required")
    coordinates = _seam_sample_coordinates(assembly)
    observations: list[RendererSeamObservation] = []
    sampled_outputs: list[NDArray[np.uint8]] = []
    for renderer, path in sorted(renderer_outputs.items()):
        try:
            with Image.open(path) as image:
                rgba = np.asarray(image.convert("RGBA"), dtype=np.uint8)
        except OSError as error:
            raise ValueError(f"cannot read {renderer} seam render: {error}") from error
        samples = np.asarray(
            [
                rgba[y, x]
                for x, y in coordinates
                if 0 <= x < rgba.shape[1] and 0 <= y < rgba.shape[0]
            ],
            dtype=np.uint8,
        )
        if samples.size == 0:
            minimum_alpha = 1.0
            gap_rate = 0.0
        else:
            alpha = samples[:, 3].astype(np.float64) / 255.0
            try:
                minimum_alpha = float(np.min(alpha))
                gap_rate = float(np.mean(alpha < 0.99))
            except (TypeError, ValueError, FloatingPointError) as error:
                raise ValueError(f"cannot aggregate {renderer} seam alpha: {error}") from error
        observations.append(
            RendererSeamObservation(renderer, len(samples), gap_rate, minimum_alpha)
        )
        sampled_outputs.append(samples)

    maximum_delta = 0.0
    if (
        sampled_outputs
        and sampled_outputs[0].size > 0
        and all(samples.shape == sampled_outputs[0].shape for samples in sampled_outputs)
    ):
        stack = np.stack(sampled_outputs).astype(np.float64) / 255.0
        try:
            maximum_delta = float(np.max(np.max(stack, axis=0) - np.min(stack, axis=0)))
        except (TypeError, ValueError, FloatingPointError) as error:
            raise ValueError(f"cannot aggregate renderer seam delta: {error}") from error
    return RendererSeamMatrix(tuple(observations), maximum_delta)
