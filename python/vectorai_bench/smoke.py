"""One-seed, two-baseline end-to-end benchmark smoke orchestration."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

from .baselines import BaselineResult, PotraceAdapter, VTracerAdapter
from .degradation import generate_degraded_variants
from .external_tools import ToolStatus
from .fixtures import generate_fixture_set
from .manifest import manifest_sha256
from .metrics.editability import measure_svg_editability
from .metrics.fidelity import compare_rgba
from .metrics.topology import TopologyObservation, analyze_binary_mask, compare_topology
from .models import DatasetManifest, DesignFamily, VariantTier
from .renderers import ResvgAdapter
from .reporting import BenchmarkReport, build_report, semantic_records_sha256, write_report

SMOKE_SCHEMA_VERSION = "1.0.0"


class SmokeBenchmarkError(RuntimeError):
    """Raised when smoke benchmark orchestration cannot complete safely."""


@dataclass(frozen=True, slots=True)
class SmokeRunResult:
    dataset_sha256: str
    semantic_records_sha256: str
    artifact_sha256: dict[str, str]
    report: BenchmarkReport
    all_baselines_succeeded: bool


def _metric(
    name: str,
    value: float,
    unit: str,
    *,
    higher_is_better: bool,
) -> dict[str, object]:
    return {
        "name": name,
        "version": "1.0.0",
        "value": value,
        "unit": unit,
        "valid": True,
        "higher_is_better": higher_is_better,
    }


def _status(status: ToolStatus) -> str:
    if status is ToolStatus.SUCCESS:
        return "success"
    if status is ToolStatus.TIMEOUT:
        return "timeout"
    if status is ToolStatus.UNAVAILABLE:
        return "unsupported"
    return "failed"


def _run_manifest_digest(result: BaselineResult, case_id: str) -> str:
    identity = result.identity
    payload = {
        "baseline": result.baseline,
        "case_id": case_id,
        "preset": result.preset,
        "arguments": list(result.arguments),
        "version": identity.version if identity is not None else "unavailable",
        "executable_sha256": (identity.executable_sha256 if identity is not None else "0" * 64),
    }
    encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(encoded).hexdigest()


def _family_and_case(manifest: DatasetManifest) -> tuple[DesignFamily, object]:
    family = next(item for item in manifest.families if item.family_id == "synthetic-ring-001")
    case = next(
        item
        for item in manifest.cases
        if item.family_id == family.family_id and item.variant.tier is VariantTier.T1
    )
    return family, case


def _write_pbm(source_path: Path, output_path: Path) -> None:
    try:
        with Image.open(source_path) as source:
            alpha = source.convert("RGBA").getchannel("A")
            threshold_lut = [0 if value >= 128 else 255 for value in range(256)]
            binary = alpha.point(threshold_lut, mode="1")
            binary.save(output_path, format="PPM")
    except OSError as error:
        raise SmokeBenchmarkError(f"cannot build PBM smoke input: {error}") from error


def _artifact(path: Path, name: str, media_type: str) -> dict[str, object]:
    try:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as error:
        raise SmokeBenchmarkError(f"cannot hash smoke artifact {path}: {error}") from error
    return {"name": name, "sha256": digest, "media_type": media_type}


def _failed_record(
    family: DesignFamily,
    case: object,
    result: BaselineResult,
) -> dict[str, object]:
    from .models import BenchmarkCase

    if not isinstance(case, BenchmarkCase):
        raise TypeError("smoke case must be a BenchmarkCase")
    identity = result.identity
    return {
        "schema_version": "1.0.0",
        "design_family_id": family.family_id,
        "case_id": case.case_id,
        "split": family.split.value,
        "primary_class": family.primary_class.value,
        "tags": list(family.tags),
        "source": {
            "sha256": case.raster_asset.sha256 if case.raster_asset is not None else "0" * 64,
            "ground_truth_sha256": (
                family.ground_truth.vector_asset.sha256
                if family.ground_truth.vector_asset is not None
                else family.source.sha256
            ),
            "provenance": family.source.provenance,
            "license_id": family.source.license_id,
        },
        "variant": case.variant.to_dict(),
        "runner": {
            "name": result.baseline,
            "version": identity.version if identity is not None else "unavailable",
            "preset": result.preset,
            "status": _status(result.status),
            "run_manifest_sha256": _run_manifest_digest(result, case.case_id),
        },
        "metrics": [],
        "artifacts": [],
    }


def _successful_record(
    family: DesignFamily,
    case: object,
    result: BaselineResult,
    vector_path: Path,
    render_path: Path,
    reference_path: Path,
) -> dict[str, object]:
    from .models import BenchmarkCase

    if not isinstance(case, BenchmarkCase) or case.raster_asset is None:
        raise TypeError("smoke case must have a raster asset")
    identity = result.identity
    if identity is None:
        raise SmokeBenchmarkError("successful baseline has no tool identity")

    try:
        with Image.open(render_path) as predicted_image:
            predicted = np.asarray(predicted_image.convert("RGBA"), dtype=np.uint8)
        with Image.open(reference_path) as reference_image:
            reference = np.asarray(
                reference_image.convert("RGBA").resize(
                    (case.variant.width, case.variant.height), Image.Resampling.LANCZOS
                ),
                dtype=np.uint8,
            )
    except OSError as error:
        raise SmokeBenchmarkError(f"cannot read smoke render: {error}") from error

    predicted_topology = analyze_binary_mask(predicted[..., 3] >= 128)
    truth = family.ground_truth.topology
    reference_topology = TopologyObservation(
        components=truth.components,
        holes=truth.holes,
        adjacency=frozenset(truth.adjacency),
        junction_degrees=truth.junction_degrees,
    )
    topology = compare_topology(reference_topology, predicted_topology)
    fidelity = compare_rgba(reference, predicted)
    editability = measure_svg_editability(
        vector_path,
        allow_known_svg_10_doctype=result.baseline == "potrace",
    )
    return {
        "schema_version": "1.0.0",
        "design_family_id": family.family_id,
        "case_id": case.case_id,
        "split": family.split.value,
        "primary_class": family.primary_class.value,
        "tags": list(family.tags),
        "source": {
            "sha256": case.raster_asset.sha256,
            "ground_truth_sha256": (
                family.ground_truth.vector_asset.sha256
                if family.ground_truth.vector_asset is not None
                else family.source.sha256
            ),
            "provenance": family.source.provenance,
            "license_id": family.source.license_id,
        },
        "variant": case.variant.to_dict(),
        "runner": {
            "name": result.baseline,
            "version": identity.version,
            "preset": result.preset,
            "status": "success",
            "run_manifest_sha256": _run_manifest_digest(result, case.case_id),
        },
        "metrics": [
            _metric(
                "exact_topology",
                1.0 if topology.exact_topology else 0.0,
                "ratio",
                higher_is_better=True,
            ),
            _metric(
                "premultiplied_rgba_rmse",
                fidelity.premultiplied_rgba_rmse,
                "normalized_error",
                higher_is_better=False,
            ),
            _metric(
                "node_count",
                editability.node_count,
                "count",
                higher_is_better=False,
            ),
            _metric(
                "wall_time_ms",
                result.wall_time_ms,
                "ms",
                higher_is_better=False,
            ),
        ],
        "artifacts": [
            _artifact(vector_path, "vector-output", "image/svg+xml"),
            _artifact(render_path, "reference-render", "image/png"),
        ],
    }


def run_smoke_benchmark(
    output_dir: Path,
    *,
    vtracer: VTracerAdapter,
    potrace: PotraceAdapter,
    renderer: ResvgAdapter,
) -> SmokeRunResult:
    dataset_dir = output_dir / "dataset"
    manifest = generate_fixture_set(dataset_dir)
    manifest = generate_degraded_variants(dataset_dir)
    family, case = _family_and_case(manifest)
    from .models import BenchmarkCase

    if not isinstance(case, BenchmarkCase) or case.raster_asset is None:
        raise SmokeBenchmarkError("selected smoke case has no raster artifact")
    raster_path = dataset_dir / case.raster_asset.artifact_ref
    reference_path = dataset_dir / f"fixtures/{family.family_id}/reference.png"
    output_dir.mkdir(parents=True, exist_ok=True)
    pbm_path = output_dir / "smoke-input.pbm"
    _write_pbm(raster_path, pbm_path)

    baseline_runs = (
        (
            vtracer.vectorize(
                raster_path,
                output_dir / "vtracer.svg",
                preset_name="faithful",
            ),
            output_dir / "vtracer.svg",
        ),
        (
            potrace.vectorize(
                pbm_path,
                output_dir / "potrace.svg",
                preset_name="faithful",
            ),
            output_dir / "potrace.svg",
        ),
    )

    records: list[dict[str, object]] = []
    artifact_hashes: dict[str, str] = {}
    all_succeeded = True
    for baseline_result, vector_path in baseline_runs:
        if baseline_result.status is not ToolStatus.SUCCESS:
            all_succeeded = False
            records.append(_failed_record(family, case, baseline_result))
            continue
        render_path = output_dir / f"{baseline_result.baseline}.png"
        render_result = renderer.render(
            vector_path,
            render_path,
            width=case.variant.width,
            height=case.variant.height,
            allow_known_svg_10_doctype=baseline_result.baseline == "potrace",
        )
        if render_result.status is not ToolStatus.SUCCESS:
            all_succeeded = False
            failed = BaselineResult(
                status=render_result.status,
                baseline=baseline_result.baseline,
                preset=baseline_result.preset,
                arguments=baseline_result.arguments,
                identity=baseline_result.identity,
                wall_time_ms=baseline_result.wall_time_ms,
                message=render_result.message,
            )
            records.append(_failed_record(family, case, failed))
            continue
        record = _successful_record(
            family,
            case,
            baseline_result,
            vector_path,
            render_path,
            reference_path,
        )
        records.append(record)
        artifact_hashes[vector_path.name] = hashlib.sha256(vector_path.read_bytes()).hexdigest()
        artifact_hashes[render_path.name] = hashlib.sha256(render_path.read_bytes()).hexdigest()

    records.sort(key=lambda item: str(_record_runner_name(item)))
    records_path = output_dir / "records.json"
    try:
        records_path.write_text(
            json.dumps(records, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    except OSError as error:
        raise SmokeBenchmarkError(f"cannot write smoke records: {error}") from error

    dataset_digest = manifest_sha256(manifest)
    report = build_report(records, dataset_sha256=dataset_digest)
    write_report(
        report,
        output_dir / "benchmark-report.json",
        output_dir / "benchmark-report.html",
    )
    return SmokeRunResult(
        dataset_sha256=dataset_digest,
        semantic_records_sha256=semantic_records_sha256(records),
        artifact_sha256=dict(sorted(artifact_hashes.items())),
        report=report,
        all_baselines_succeeded=all_succeeded,
    )


def _record_runner_name(record: dict[str, object]) -> str:
    runner = record.get("runner")
    return str(runner.get("name", "")) if isinstance(runner, dict) else ""


def verify_repeatability(first: SmokeRunResult, second: SmokeRunResult) -> None:
    if first.dataset_sha256 != second.dataset_sha256:
        raise SmokeBenchmarkError("dataset manifest digest changed between smoke runs")
    if first.semantic_records_sha256 != second.semantic_records_sha256:
        raise SmokeBenchmarkError("semantic benchmark digest changed between smoke runs")
    if first.artifact_sha256 != second.artifact_sha256:
        raise SmokeBenchmarkError("baseline artifact digests changed between smoke runs")
