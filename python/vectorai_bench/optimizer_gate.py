"""Locked E5 optimizer ablation and Gate G4 evaluation."""

from __future__ import annotations

import hashlib
import json
import math
import statistics
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, cast

from vectorai_engine.multicolor_pipeline import MulticolorPipelineConfig, run_multicolor_pipeline
from vectorai_engine.profiles import OptimizationMode, load_optimizer_profiles

from .multicolor_gate import generate_multicolor_cases


@dataclass(frozen=True, slots=True)
class OptimizerCaseMeasurement:
    case_id: str
    exact_topology: bool
    fallback_used: bool
    baseline_node_count: int
    optimized_node_count: int
    baseline_rmse: float
    optimized_rmse: float
    fidelity_improvement: float
    node_advantage: float
    baseline_runtime_ms: float
    optimized_runtime_ms: float
    optimizer_stage_ms: dict[str, float]


@dataclass(frozen=True, slots=True)
class OptimizerGateEvaluation:
    passed: bool
    case_count: int
    exact_topology_rate: float
    fallback_count: int
    node_regression_count: int
    median_fidelity_improvement: float
    mean_fidelity_improvement: float
    improved_case_count: int
    fidelity_regression_count: int
    median_node_advantage: float
    optimized_runtime_p95_ms: float
    criteria: dict[str, bool]


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"cannot read optimizer gate artifact {path.name}: {error}") from error
    if not isinstance(payload, dict):
        raise RuntimeError(f"optimizer gate artifact must be an object: {path.name}")
    return cast(dict[str, Any], payload)


def _topology_projection(scene: dict[str, Any]) -> object:
    return {
        "palette_count": scene["palette"]["selected_color_count"],
        "region_count": scene["segmentation"]["region_count"],
        "graph": scene["graph"],
        "junctions": scene["junctions"],
        "shared_boundaries": scene["shared_boundaries"],
    }


def _finite_float(value: object, context: str) -> float:
    try:
        result = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError) as error:
        raise RuntimeError(f"{context} must be numeric") from error
    if not math.isfinite(result):
        raise RuntimeError(f"{context} must be finite")
    return result


def _nonnegative_int(value: object, context: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise RuntimeError(f"{context} must be a nonnegative integer")
    return value


def _percentile_95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, (95 * len(ordered) + 99) // 100 - 1))
    return ordered[index]


def optimizer_semantic_digest(
    measurements: list[OptimizerCaseMeasurement],
    evaluation: OptimizerGateEvaluation,
    profile_set_sha256: str,
    profile_sha256: str,
) -> str:
    evaluation_projection = asdict(evaluation)
    evaluation_projection.pop("passed")
    evaluation_projection.pop("optimized_runtime_p95_ms")
    criteria = cast(dict[str, bool], evaluation_projection["criteria"])
    evaluation_projection["criteria"] = {
        key: value for key, value in criteria.items() if key != "runtime_p95_within_20s"
    }
    projection = {
        "schema_version": "1.0.0",
        "profile_set_sha256": profile_set_sha256,
        "profile_sha256": profile_sha256,
        "cases": [
            {
                key: value
                for key, value in asdict(item).items()
                if key
                not in {
                    "baseline_runtime_ms",
                    "optimized_runtime_ms",
                    "optimizer_stage_ms",
                }
            }
            for item in measurements
        ],
        "evaluation": evaluation_projection,
    }
    payload = json.dumps(
        projection,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def evaluate_optimizer_g4(
    measurements: list[OptimizerCaseMeasurement],
    *,
    runtime_limit_ms: float = 20_000.0,
    fidelity_noise_floor: float = 1.0e-4,
    minimum_improved_cases: int = 3,
) -> OptimizerGateEvaluation:
    case_count = len(measurements)
    if case_count < 1:
        raise ValueError("optimizer G4 requires at least one case")
    exact_topology_rate = sum(item.exact_topology for item in measurements) / case_count
    fallback_count = sum(item.fallback_used for item in measurements)
    node_regression_count = sum(
        item.optimized_node_count > item.baseline_node_count for item in measurements
    )
    fidelity_improvements = [item.fidelity_improvement for item in measurements]
    node_advantages = [item.node_advantage for item in measurements]
    runtime_p95 = _percentile_95([item.optimized_runtime_ms for item in measurements])
    median_fidelity = statistics.median(fidelity_improvements)
    mean_fidelity = statistics.fmean(fidelity_improvements)
    improved_case_count = sum(value > fidelity_noise_floor for value in fidelity_improvements)
    fidelity_regression_count = sum(value < -1.0e-12 for value in fidelity_improvements)
    criteria = {
        "exact_topology": exact_topology_rate == 1.0,
        "zero_fallback": fallback_count == 0,
        "zero_node_regression": node_regression_count == 0,
        "zero_fidelity_regression": fidelity_regression_count == 0,
        "measurable_mean_fidelity_gain": mean_fidelity > fidelity_noise_floor,
        "minimum_three_improved_cases": improved_case_count >= minimum_improved_cases,
        "runtime_p95_within_20s": runtime_p95 <= runtime_limit_ms,
    }
    return OptimizerGateEvaluation(
        passed=all(criteria.values()),
        case_count=case_count,
        exact_topology_rate=exact_topology_rate,
        fallback_count=fallback_count,
        node_regression_count=node_regression_count,
        median_fidelity_improvement=median_fidelity,
        mean_fidelity_improvement=mean_fidelity,
        improved_case_count=improved_case_count,
        fidelity_regression_count=fidelity_regression_count,
        median_node_advantage=statistics.median(node_advantages),
        optimized_runtime_p95_ms=runtime_p95,
        criteria=criteria,
    )


def run_optimizer_gate(
    output_directory: Path,
    *,
    resvg_executable: Path,
    profile_path: Path,
    mode: OptimizationMode = OptimizationMode.MINIMAL,
) -> OptimizerGateEvaluation:
    if output_directory.exists():
        raise ValueError(f"optimizer gate output already exists: {output_directory}")
    output_directory.mkdir(parents=True)
    cases = generate_multicolor_cases(output_directory / "fixtures")
    profile_set = load_optimizer_profiles(profile_path)
    profile = profile_set.select(mode)
    measurements: list[OptimizerCaseMeasurement] = []
    for case in cases:
        baseline = run_multicolor_pipeline(
            case.source_path,
            output_directory / "runs" / case.case_id / "baseline",
            MulticolorPipelineConfig(resvg_executable=resvg_executable),
        )
        optimized = run_multicolor_pipeline(
            case.source_path,
            output_directory / "runs" / case.case_id / "optimized",
            MulticolorPipelineConfig(
                resvg_executable=resvg_executable,
                optimizer_profile_path=profile_path,
                optimizer_mode=mode,
            ),
        )
        baseline_scene = _load_json(baseline.scene_path)
        optimized_scene = _load_json(optimized.scene_path)
        baseline_manifest = _load_json(baseline.manifest_path)
        optimized_manifest = _load_json(optimized.manifest_path)
        optimizer = optimized_scene.get("optimizer")
        if not isinstance(optimizer, dict):
            raise RuntimeError(f"optimizer metadata missing for {case.case_id}")
        optimizer_payload = cast(dict[str, Any], optimizer)
        render_rank = cast(dict[str, Any], optimizer_payload["render_rank"])
        winner_id = str(render_rank["winner_id"])
        baseline_id = "tolerance-0.750000"
        scores = cast(list[dict[str, Any]], render_rank["scores"])
        score_by_id = {
            str(item["candidate_id"]): _finite_float(
                item["aggregate_rmse"], "render-rank aggregate RMSE"
            )
            for item in scores
        }
        if baseline_id not in score_by_id or winner_id not in score_by_id:
            raise RuntimeError(f"optimizer ablation scores incomplete for {case.case_id}")
        baseline_nodes = _nonnegative_int(
            baseline_scene["scene"]["editability"]["node_count"],
            "baseline node count",
        )
        optimized_nodes = _nonnegative_int(
            optimizer_payload["selected_node_count"],
            "optimized node count",
        )
        baseline_rmse = score_by_id[baseline_id]
        optimized_rmse = score_by_id[winner_id]
        timing_items = cast(list[dict[str, Any]], optimizer_payload["stage_timings"])
        optimizer_stage_ms = {
            str(item["stage"]): _finite_float(item["duration_ms"], "optimizer stage timing")
            for item in timing_items
        }
        measurements.append(
            OptimizerCaseMeasurement(
                case_id=case.case_id,
                exact_topology=_topology_projection(baseline_scene)
                == _topology_projection(optimized_scene),
                fallback_used=bool(optimizer_payload["fallback_used"]),
                baseline_node_count=baseline_nodes,
                optimized_node_count=optimized_nodes,
                baseline_rmse=baseline_rmse,
                optimized_rmse=optimized_rmse,
                fidelity_improvement=baseline_rmse - optimized_rmse,
                node_advantage=(baseline_nodes - optimized_nodes) / baseline_nodes,
                baseline_runtime_ms=_finite_float(
                    baseline_manifest["total_duration_ms"], "baseline runtime"
                ),
                optimized_runtime_ms=_finite_float(
                    optimized_manifest["total_duration_ms"], "optimized runtime"
                ),
                optimizer_stage_ms=optimizer_stage_ms,
            )
        )
    evaluation = evaluate_optimizer_g4(measurements)
    report = {
        "schema_version": "1.0.0",
        "gate": "G4",
        "mode": mode.value,
        "profile_set_sha256": profile_set.sha256,
        "profile_sha256": profile.sha256,
        "semantic_digest": optimizer_semantic_digest(
            measurements,
            evaluation,
            profile_set.sha256,
            profile.sha256,
        ),
        "cases": [asdict(item) for item in measurements],
        "evaluation": asdict(evaluation),
    }
    (output_directory / "g4-report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return evaluation
