from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from vectorai_bench.reporting import (
    GatePolicy,
    build_report,
    report_html,
    report_json,
    semantic_records_sha256,
    write_report,
)


def metric(name: str, value: float) -> dict[str, object]:
    return {
        "name": name,
        "version": "1.0.0",
        "value": value,
        "unit": "ratio" if name == "exact_topology" else "value",
        "valid": True,
    }


def record(
    case_id: str,
    runner: str,
    *,
    topology: float,
    fidelity: float,
    nodes: float,
    wall_ms: float,
) -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "case_id": case_id,
        "runner": {
            "name": runner,
            "version": "1.0",
            "preset": "faithful",
            "status": "success",
            "run_manifest_sha256": "a" * 64,
        },
        "metrics": [
            metric("exact_topology", topology),
            metric("premultiplied_rgba_rmse", fidelity),
            metric("node_count", nodes),
            metric("wall_time_ms", wall_ms),
        ],
    }


def sample_records() -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for case_id in ("case-a", "case-b"):
        records.extend(
            (
                record(case_id, "bad-topology", topology=0, fidelity=0.001, nodes=2, wall_ms=1),
                record(case_id, "faithful", topology=1, fidelity=0.0100, nodes=20, wall_ms=12),
                record(case_id, "minimal", topology=1, fidelity=0.0101, nodes=8, wall_ms=8),
            )
        )
    return records


def test_ordered_gates_never_reward_bad_topology_for_fidelity() -> None:
    report = build_report(
        sample_records(),
        dataset_sha256="b" * 64,
        policy=GatePolicy(minimum_topology_rate=1.0, fidelity_relative_tolerance=0.02),
    )
    assert all("bad-topology" not in key for key in report.gates.topology_passed)
    assert report.gates.node_ranking == (
        "minimal:1.0:faithful",
        "faithful:1.0:faithful",
    )


def test_pareto_frontier_retains_tradeoffs_after_topology_gate() -> None:
    report = build_report(sample_records(), dataset_sha256="b" * 64)
    assert "bad-topology:1.0:faithful" not in report.pareto_frontier
    assert "faithful:1.0:faithful" in report.pareto_frontier
    assert "minimal:1.0:faithful" in report.pareto_frontier


def test_report_is_deterministic_under_record_reordering() -> None:
    records = sample_records()
    first = build_report(records, dataset_sha256="c" * 64)
    second = build_report(list(reversed(records)), dataset_sha256="c" * 64)
    assert report_json(first) == report_json(second)


def test_semantic_digest_excludes_observational_runtime() -> None:
    first = sample_records()
    second = deepcopy(first)
    second[0]["metrics"][-1]["value"] = 9999.0  # type: ignore[index]
    second[0]["runner"]["run_manifest_sha256"] = "d" * 64  # type: ignore[index]
    assert semantic_records_sha256(first) == semantic_records_sha256(second)


def test_json_and_html_reports_are_written_and_html_is_escaped(tmp_path: Path) -> None:
    records = sample_records()
    records[0]["runner"]["name"] = "<unsafe>"  # type: ignore[index]
    report = build_report(records, dataset_sha256="e" * 64)
    json_path = tmp_path / "report.json"
    html_path = tmp_path / "report.html"
    write_report(report, json_path, html_path)
    assert json_path.read_text(encoding="utf-8") == report_json(report)
    html_payload = html_path.read_text(encoding="utf-8")
    assert html_payload == report_html(report)
    assert "&lt;unsafe&gt;" in html_payload
    assert "<unsafe>" not in html_payload
