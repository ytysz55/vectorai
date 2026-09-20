"""Deterministic benchmark aggregation, ordered gates, and Pareto reporting."""

from __future__ import annotations

import hashlib
import html
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

REPORT_SCHEMA_VERSION = "1.0.0"
OBSERVATIONAL_METRICS = frozenset({"wall_time_ms", "cpu_time_ms", "peak_rss_bytes"})


class ReportError(ValueError):
    """Raised when benchmark records cannot produce a valid report."""


@dataclass(frozen=True, slots=True)
class GatePolicy:
    minimum_topology_rate: float = 0.95
    fidelity_relative_tolerance: float = 0.02
    fidelity_absolute_tolerance: float = 1e-6

    def __post_init__(self) -> None:
        if not 0.0 <= self.minimum_topology_rate <= 1.0:
            raise ValueError("minimum_topology_rate must be in [0, 1]")
        if self.fidelity_relative_tolerance < 0.0 or self.fidelity_absolute_tolerance < 0.0:
            raise ValueError("fidelity tolerances cannot be negative")


@dataclass(frozen=True, slots=True)
class RunnerSummary:
    runner_key: str
    runner_name: str
    runner_version: str
    preset: str
    case_count: int
    success_count: int
    topology_pass_rate: float
    mean_fidelity: float | None
    mean_node_count: float | None
    mean_wall_time_ms: float | None

    def to_dict(self) -> dict[str, object]:
        return {
            "runner_key": self.runner_key,
            "runner_name": self.runner_name,
            "runner_version": self.runner_version,
            "preset": self.preset,
            "case_count": self.case_count,
            "success_count": self.success_count,
            "topology_pass_rate": self.topology_pass_rate,
            "mean_fidelity": self.mean_fidelity,
            "mean_node_count": self.mean_node_count,
            "mean_wall_time_ms": self.mean_wall_time_ms,
        }


@dataclass(frozen=True, slots=True)
class GateResult:
    topology_passed: tuple[str, ...]
    fidelity_passed: tuple[str, ...]
    node_ranking: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "topology_passed": list(self.topology_passed),
            "fidelity_passed": list(self.fidelity_passed),
            "node_ranking": list(self.node_ranking),
        }


@dataclass(frozen=True, slots=True)
class BenchmarkReport:
    dataset_sha256: str
    semantic_records_sha256: str
    summaries: tuple[RunnerSummary, ...]
    gates: GateResult
    pareto_frontier: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": REPORT_SCHEMA_VERSION,
            "dataset_sha256": self.dataset_sha256,
            "semantic_records_sha256": self.semantic_records_sha256,
            "gates": self.gates.to_dict(),
            "pareto_frontier": list(self.pareto_frontier),
            "summaries": [summary.to_dict() for summary in self.summaries],
        }


def _mapping(value: object, path: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ReportError(f"{path} must be an object")
    return cast(dict[str, object], value)


def _string(value: object, path: str) -> str:
    if not isinstance(value, str) or not value:
        raise ReportError(f"{path} must be a non-empty string")
    return value


def _number(value: object, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ReportError(f"{path} must be numeric")
    try:
        return float(value)
    except (TypeError, ValueError, OverflowError) as error:
        raise ReportError(f"{path} cannot be converted to a finite number") from error


def _runner_key(record: dict[str, object]) -> tuple[str, str, str, str]:
    runner = _mapping(record.get("runner"), "runner")
    name = _string(runner.get("name"), "runner.name")
    version = _string(runner.get("version"), "runner.version")
    preset = _string(runner.get("preset"), "runner.preset")
    return f"{name}:{version}:{preset}", name, version, preset


def _metrics(record: dict[str, object]) -> dict[str, float]:
    raw_metrics = record.get("metrics")
    if not isinstance(raw_metrics, list):
        raise ReportError("metrics must be an array")
    metrics: dict[str, float] = {}
    for index, raw_metric in enumerate(raw_metrics):
        metric = _mapping(raw_metric, f"metrics[{index}]")
        valid = metric.get("valid")
        if not isinstance(valid, bool) or not valid:
            continue
        name = _string(metric.get("name"), f"metrics[{index}].name")
        if name in metrics:
            raise ReportError(f"duplicate metric {name!r}")
        metrics[name] = _number(metric.get("value"), f"metrics[{index}].value")
    return metrics


def semantic_records_projection(records: list[dict[str, object]]) -> list[dict[str, object]]:
    projected: list[dict[str, object]] = []
    for record in records:
        clone = dict(record)
        metrics = record.get("metrics")
        if isinstance(metrics, list):
            clone["metrics"] = [
                dict(metric)
                for metric in metrics
                if isinstance(metric, dict) and metric.get("name") not in OBSERVATIONAL_METRICS
            ]
        runner = record.get("runner")
        if isinstance(runner, dict):
            runner_clone = dict(runner)
            runner_clone.pop("run_manifest_sha256", None)
            clone["runner"] = runner_clone
        projected.append(clone)
    return sorted(
        projected,
        key=lambda item: (
            str(item.get("case_id", "")),
            str(_mapping(item.get("runner"), "runner").get("name", "")),
            str(_mapping(item.get("runner"), "runner").get("preset", "")),
        ),
    )


def semantic_records_sha256(records: list[dict[str, object]]) -> str:
    payload = semantic_records_projection(records)
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(encoded.encode()).hexdigest()


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def summarize_records(records: list[dict[str, object]]) -> tuple[RunnerSummary, ...]:
    grouped: dict[str, list[dict[str, object]]] = {}
    identities: dict[str, tuple[str, str, str]] = {}
    for record in records:
        key, name, version, preset = _runner_key(record)
        grouped.setdefault(key, []).append(record)
        identities[key] = (name, version, preset)

    summaries: list[RunnerSummary] = []
    for key in sorted(grouped):
        group = grouped[key]
        success_count = 0
        topology_passes = 0
        fidelity_values: list[float] = []
        node_values: list[float] = []
        runtime_values: list[float] = []
        for record in group:
            runner = _mapping(record.get("runner"), "runner")
            if runner.get("status") != "success":
                continue
            success_count += 1
            metrics = _metrics(record)
            exact_topology = metrics.get("exact_topology", 0.0) >= 0.5
            if exact_topology:
                topology_passes += 1
                if "premultiplied_rgba_rmse" in metrics:
                    fidelity_values.append(metrics["premultiplied_rgba_rmse"])
                if "node_count" in metrics:
                    node_values.append(metrics["node_count"])
            if "wall_time_ms" in metrics:
                runtime_values.append(metrics["wall_time_ms"])
        name, version, preset = identities[key]
        summaries.append(
            RunnerSummary(
                runner_key=key,
                runner_name=name,
                runner_version=version,
                preset=preset,
                case_count=len(group),
                success_count=success_count,
                topology_pass_rate=topology_passes / len(group),
                mean_fidelity=_mean(fidelity_values),
                mean_node_count=_mean(node_values),
                mean_wall_time_ms=_mean(runtime_values),
            )
        )
    return tuple(summaries)


def apply_ordered_gates(summaries: tuple[RunnerSummary, ...], policy: GatePolicy) -> GateResult:
    topology_passed = tuple(
        summary.runner_key
        for summary in summaries
        if summary.topology_pass_rate >= policy.minimum_topology_rate
    )
    topology_set = set(topology_passed)
    fidelity_candidates = [
        summary
        for summary in summaries
        if summary.runner_key in topology_set and summary.mean_fidelity is not None
    ]
    if fidelity_candidates:
        best_fidelity = min(cast(float, summary.mean_fidelity) for summary in fidelity_candidates)
        threshold = (
            best_fidelity * (1.0 + policy.fidelity_relative_tolerance)
            + policy.fidelity_absolute_tolerance
        )
        fidelity_passed = tuple(
            summary.runner_key
            for summary in fidelity_candidates
            if cast(float, summary.mean_fidelity) <= threshold
        )
    else:
        fidelity_passed = ()
    fidelity_set = set(fidelity_passed)
    node_ranking = tuple(
        summary.runner_key
        for summary in sorted(
            (
                item
                for item in summaries
                if item.runner_key in fidelity_set and item.mean_node_count is not None
            ),
            key=lambda item: (cast(float, item.mean_node_count), item.runner_key),
        )
    )
    return GateResult(topology_passed, fidelity_passed, node_ranking)


def pareto_frontier(summaries: tuple[RunnerSummary, ...]) -> tuple[str, ...]:
    eligible = [
        summary
        for summary in summaries
        if summary.mean_fidelity is not None and summary.mean_node_count is not None
    ]

    def objectives(summary: RunnerSummary) -> tuple[float, float, float]:
        return (
            1.0 - summary.topology_pass_rate,
            cast(float, summary.mean_fidelity),
            cast(float, summary.mean_node_count),
        )

    frontier: list[str] = []
    for candidate in eligible:
        candidate_values = objectives(candidate)
        dominated = any(
            other.runner_key != candidate.runner_key
            and all(
                left <= right
                for left, right in zip(objectives(other), candidate_values, strict=True)
            )
            and any(
                left < right
                for left, right in zip(objectives(other), candidate_values, strict=True)
            )
            for other in eligible
        )
        if not dominated:
            frontier.append(candidate.runner_key)
    return tuple(sorted(frontier))


def build_report(
    records: list[dict[str, object]],
    *,
    dataset_sha256: str,
    policy: GatePolicy | None = None,
) -> BenchmarkReport:
    if not records:
        raise ReportError("at least one benchmark record is required")
    if len(dataset_sha256) != 64:
        raise ReportError("dataset_sha256 must contain 64 hexadecimal characters")
    summaries = summarize_records(records)
    active_policy = GatePolicy() if policy is None else policy
    return BenchmarkReport(
        dataset_sha256=dataset_sha256,
        semantic_records_sha256=semantic_records_sha256(records),
        summaries=summaries,
        gates=apply_ordered_gates(summaries, active_policy),
        pareto_frontier=pareto_frontier(summaries),
    )


def report_json(report: BenchmarkReport) -> str:
    return json.dumps(report.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def report_html(report: BenchmarkReport) -> str:
    rows = []
    frontier = set(report.pareto_frontier)
    for summary in report.summaries:
        fidelity = "—" if summary.mean_fidelity is None else f"{summary.mean_fidelity:.6f}"
        nodes = "—" if summary.mean_node_count is None else f"{summary.mean_node_count:.1f}"
        runtime = "—" if summary.mean_wall_time_ms is None else f"{summary.mean_wall_time_ms:.2f}"
        rows.append(
            "<tr>"
            f"<td>{html.escape(summary.runner_key)}</td>"
            f"<td>{summary.topology_pass_rate:.1%}</td>"
            f"<td>{fidelity}</td><td>{nodes}</td><td>{runtime}</td>"
            f"<td>{'yes' if summary.runner_key in frontier else 'no'}</td>"
            "</tr>"
        )
    gate_order = (
        " → ".join(html.escape(item) for item in report.gates.node_ranking)
        or "No runner passed all gates"
    )
    return (
        '<!doctype html><html lang="en"><meta charset="utf-8">'
        "<title>VectorAI benchmark report</title>"
        "<style>body{font-family:system-ui;max-width:1100px;margin:2rem auto}"
        "table{border-collapse:collapse;width:100%}th,td{border:1px solid #ccc;"
        "padding:.45rem;text-align:right}th:first-child,td:first-child{text-align:left}</style>"
        "<h1>VectorAI benchmark report</h1>"
        f"<p>Dataset: <code>{html.escape(report.dataset_sha256)}</code></p>"
        f"<p>Topology → fidelity → node ranking: {gate_order}</p>"
        "<table><thead><tr><th>Runner</th><th>Exact topology</th><th>RGBA RMSE</th>"
        "<th>Nodes</th><th>Wall ms</th><th>Pareto</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table></html>\n"
    )


def write_report(report: BenchmarkReport, json_path: Path, html_path: Path) -> None:
    try:
        json_path.parent.mkdir(parents=True, exist_ok=True)
        html_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(report_json(report), encoding="utf-8", newline="\n")
        html_path.write_text(report_html(report), encoding="utf-8", newline="\n")
    except OSError as error:
        raise ReportError(f"cannot write benchmark report: {error}") from error


def load_records(path: Path) -> list[dict[str, object]]:
    try:
        payload: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ReportError(f"cannot load benchmark records {path}: {error}") from error
    if not isinstance(payload, list):
        raise ReportError("benchmark record file must contain a JSON array")
    return [_mapping(item, f"records[{index}]") for index, item in enumerate(payload)]
