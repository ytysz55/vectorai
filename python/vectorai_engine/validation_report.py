"""Schema-compatible deterministic validation evidence for generated SVG scenes."""

from __future__ import annotations

import hashlib

from .topology_validation import FindingSeverity, TopologyGeometryResult


def geometry_validation_report(
    result: TopologyGeometryResult,
    *,
    job_id: str,
    source_sha256: str,
    svg_bytes: bytes,
) -> dict[str, object]:
    """Build the v1 report; renderer timing and machine identity are not included."""

    hard_count = sum(item.severity is FindingSeverity.HARD for item in result.findings)
    soft_count = sum(item.severity is FindingSeverity.SOFT for item in result.findings)
    return {
        "schema_version": "1.0.0",
        "job_id": job_id,
        "status": "failed" if hard_count else "needs_review" if soft_count else "passed",
        "source_sha256": source_sha256,
        "svg_sha256": hashlib.sha256(svg_bytes).hexdigest(),
        "gates": [
            {
                "id": finding.code,
                "category": finding.category,
                "severity": finding.severity.value,
                "outcome": "failed",
                "message": finding.message,
                "entity_ids": list(finding.entity_ids),
            }
            for finding in result.findings
        ]
        or [
            {
                "id": "TOPOLOGY.GRAPH_INVARIANTS",
                "category": "topology",
                "severity": "hard",
                "outcome": "passed",
                "message": "Scene and graph geometry invariants hold",
            }
        ],
        "summary": {
            "hard_failures": hard_count,
            "soft_failures": soft_count,
            "warnings": soft_count,
        },
    }
