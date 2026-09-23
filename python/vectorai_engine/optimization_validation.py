"""Hard, non-compensable topology validation for E5 optimization."""

from __future__ import annotations

from dataclasses import dataclass, fields


@dataclass(frozen=True, slots=True)
class TopologySignature:
    components: int
    holes: int
    adjacency: tuple[tuple[int, int], ...]
    face_cycles: tuple[tuple[int, ...], ...]
    canonical_edge_owners: tuple[tuple[int, int, int], ...]
    shared_geometry_keys: tuple[str, ...]
    closed_cycles: tuple[bool, ...]
    stroke_edges: tuple[tuple[int, int], ...]
    junction_valence: tuple[tuple[int, int], ...]
    path_count: int
    node_count: int

    def __post_init__(self) -> None:
        if min(self.components, self.holes, self.path_count, self.node_count) < 0:
            raise ValueError("topology signature counts must be nonnegative")
        if self.adjacency != tuple(sorted(self.adjacency)):
            raise ValueError("topology adjacency must use canonical ordering")
        if self.canonical_edge_owners != tuple(sorted(self.canonical_edge_owners)):
            raise ValueError("canonical edge ownership must use canonical ordering")
        if self.shared_geometry_keys != tuple(sorted(self.shared_geometry_keys)):
            raise ValueError("shared geometry keys must use canonical ordering")
        if self.stroke_edges != tuple(sorted(self.stroke_edges)):
            raise ValueError("stroke connectivity must use canonical ordering")
        if self.junction_valence != tuple(sorted(self.junction_valence)):
            raise ValueError("junction valence must use canonical ordering")


@dataclass(frozen=True, slots=True)
class HardValidationResult:
    valid: bool
    violations: tuple[str, ...]


def compare_topology_signatures(
    baseline: TopologySignature,
    candidate: TopologySignature,
) -> HardValidationResult:
    violations = tuple(
        f"{field.name}_changed"
        for field in fields(TopologySignature)
        if getattr(baseline, field.name) != getattr(candidate, field.name)
    )
    return HardValidationResult(valid=not violations, violations=violations)
