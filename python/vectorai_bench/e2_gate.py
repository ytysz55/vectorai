"""E2 binary benchmark, ablations, and Gate G1 evaluation."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from vectorai_engine.errors import EngineFailure
from vectorai_engine.pipeline import BinaryPipelineConfig, run_binary_pipeline

from .baselines import PotraceAdapter, VTracerAdapter
from .external_tools import ToolStatus
from .metrics.editability import measure_svg_editability
from .metrics.fidelity import compare_rgba
from .metrics.topology import TopologyObservation, analyze_binary_mask, compare_topology
from .renderers import ResvgAdapter

E2_GATE_SCHEMA_VERSION = "1.0.0"


class E2GateError(RuntimeError):
    """Raised when the E2 gate cannot be evaluated safely."""


@dataclass(frozen=True, slots=True)
class E2Case:
    case_id: str
    source_path: Path
    reference_path: Path
    topology: TopologyObservation


@dataclass(frozen=True, slots=True)
class E2Measurement:
    case_id: str
    runner: str
    status: str
    exact_topology: bool | None
    premultiplied_rgba_rmse: float | None
    node_count: int | None
    wall_time_ms: float | None
    message: str = ""


@dataclass(frozen=True, slots=True)
class GateEvaluation:
    passed: bool
    exact_topology_rate: float
    shared_boundary_invariant_rate: float
    hard_failure_count: int
    baseline_node_advantage: dict[str, float | None]
    baseline_comparison_count: dict[str, int]
    no_subpixel_rmse_delta: float | None
    bezier_only_node_delta: float | None
    criteria: dict[str, bool]


def _draw_case(index: int, *, size: int = 128, scale: int = 4) -> Image.Image:
    canvas = Image.new("RGBA", (size * scale, size * scale), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    offset = index % scale
    kind = index % 4
    if kind == 0:
        draw.rectangle(
            (20 * scale + offset, 24 * scale, 106 * scale + offset, 102 * scale),
            fill=(0, 0, 0, 255),
        )
    elif kind == 1:
        draw.ellipse(
            (18 * scale + offset, 18 * scale, 110 * scale + offset, 110 * scale),
            fill=(0, 0, 0, 255),
        )
    elif kind == 2:
        draw.ellipse(
            (12 * scale + offset, 12 * scale, 116 * scale + offset, 116 * scale),
            fill=(0, 0, 0, 255),
        )
        draw.ellipse(
            (42 * scale + offset, 42 * scale, 86 * scale + offset, 86 * scale),
            fill=(0, 0, 0, 0),
        )
    else:
        draw.rectangle(
            (10 * scale + offset, 18 * scale, 54 * scale + offset, 104 * scale),
            fill=(0, 0, 0, 255),
        )
        draw.ellipse(
            (72 * scale - offset, 34 * scale, 118 * scale - offset, 80 * scale),
            fill=(0, 0, 0, 255),
        )
    return canvas.resize((size, size), Image.Resampling.LANCZOS)


def generate_e2_cases(output_directory: Path, *, count: int = 20) -> tuple[E2Case, ...]:
    if count < 4:
        raise ValueError("E2 corpus requires at least four cases")
    output_directory.mkdir(parents=True, exist_ok=True)
    cases: list[E2Case] = []
    for index in range(count):
        reference = _draw_case(index)
        source = reference.filter(ImageFilter.GaussianBlur(radius=0.35 + 0.05 * (index % 3)))
        case_id = f"binary-e2-{index:03d}"
        reference_path = output_directory / f"{case_id}-reference.png"
        source_path = output_directory / f"{case_id}-source.png"
        reference.save(reference_path, format="PNG", optimize=False, compress_level=9)
        source.save(source_path, format="PNG", optimize=False, compress_level=9)
        kind = index % 4
        topology = TopologyObservation(
            components=2 if kind == 3 else 1,
            holes=1 if kind == 2 else 0,
            adjacency=frozenset(),
            junction_degrees=(),
        )
        cases.append(E2Case(case_id, source_path, reference_path, topology))
    return tuple(cases)


def _read_rgba(path: Path) -> np.ndarray:
    try:
        with Image.open(path) as image:
            return np.asarray(image.convert("RGBA"), dtype=np.uint8)
    except OSError as error:
        raise E2GateError(f"cannot read benchmark image {path}: {error}") from error


def _measurement(
    case: E2Case,
    runner: str,
    svg_path: Path,
    render_path: Path,
    wall_time_ms: float,
) -> E2Measurement:
    predicted = _read_rgba(render_path)
    reference = _read_rgba(case.reference_path)
    topology = compare_topology(case.topology, analyze_binary_mask(predicted[..., 3] >= 128))
    fidelity = compare_rgba(reference, predicted)
    editability = measure_svg_editability(
        svg_path,
        allow_known_svg_10_doctype=runner == "potrace",
    )
    return E2Measurement(
        case_id=case.case_id,
        runner=runner,
        status="success",
        exact_topology=topology.exact_topology,
        premultiplied_rgba_rmse=fidelity.premultiplied_rgba_rmse,
        node_count=editability.node_count,
        wall_time_ms=wall_time_ms,
    )


def _failed(case: E2Case, runner: str, message: str) -> E2Measurement:
    return E2Measurement(case.case_id, runner, "failed", None, None, None, None, message)


def _run_engine(
    case: E2Case,
    output_directory: Path,
    *,
    native_executable: Path,
    resvg_executable: Path,
    runner: str,
    subpixel: bool,
    bezier_only: bool,
) -> E2Measurement:
    try:
        bundle = run_binary_pipeline(
            case.source_path,
            output_directory,
            BinaryPipelineConfig(
                native_executable=native_executable,
                resvg_executable=resvg_executable,
                subpixel=subpixel,
                bezier_only=bezier_only,
                validate_auxiliary_renderers=False,
            ),
        )
        preview = bundle.output_directory / "preview.png"
        manifest = json.loads(bundle.manifest_path.read_text(encoding="utf-8"))
        wall_time = float(manifest["resources"]["total_duration_ms"])
        return _measurement(case, runner, bundle.svg_path, preview, wall_time)
    except (EngineFailure, OSError, ValueError, KeyError, TypeError, E2GateError) as error:
        return _failed(case, runner, str(error))


def _write_pbm(source_path: Path, output_path: Path) -> None:
    try:
        with Image.open(source_path) as image:
            alpha = image.convert("RGBA").getchannel("A")
            binary = alpha.point([0 if value >= 128 else 255 for value in range(256)], mode="1")
            binary.save(output_path, format="PPM")
    except OSError as error:
        raise E2GateError(f"cannot build Potrace input: {error}") from error


def _run_baselines(
    case: E2Case,
    output_directory: Path,
    *,
    vtracer: VTracerAdapter,
    potrace: PotraceAdapter,
    renderer: ResvgAdapter,
) -> tuple[E2Measurement, E2Measurement]:
    output_directory.mkdir(parents=True, exist_ok=True)
    pbm_path = output_directory / "input.pbm"
    _write_pbm(case.source_path, pbm_path)
    runs = (
        (
            "vtracer",
            vtracer.vectorize(
                case.source_path,
                output_directory / "vtracer.svg",
                preset_name="faithful",
            ),
        ),
        (
            "potrace",
            potrace.vectorize(
                pbm_path,
                output_directory / "potrace.svg",
                preset_name="faithful",
            ),
        ),
    )
    measurements: list[E2Measurement] = []
    for runner, result in runs:
        svg_path = output_directory / f"{runner}.svg"
        if result.status is not ToolStatus.SUCCESS:
            measurements.append(_failed(case, runner, result.message or result.status.value))
            continue
        render_path = output_directory / f"{runner}.png"
        rendered = renderer.render(
            svg_path,
            render_path,
            width=128,
            height=128,
            allow_known_svg_10_doctype=runner == "potrace",
        )
        if rendered.status is not ToolStatus.SUCCESS:
            measurements.append(_failed(case, runner, rendered.message or rendered.status.value))
            continue
        try:
            measurements.append(
                _measurement(case, runner, svg_path, render_path, result.wall_time_ms)
            )
        except (ValueError, E2GateError) as error:
            measurements.append(_failed(case, runner, str(error)))
    return measurements[0], measurements[1]


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def evaluate_g1(
    measurements: list[E2Measurement],
    *,
    case_count: int,
    fidelity_band: float = 0.03,
) -> GateEvaluation:
    if case_count < 1 or not 0.0 <= fidelity_band <= 1.0:
        raise ValueError("case_count and fidelity_band are invalid")
    by_key = {(item.case_id, item.runner): item for item in measurements}
    auto = [item for item in measurements if item.runner == "engine-auto"]
    exact_count = sum(item.status == "success" and bool(item.exact_topology) for item in auto)
    success_count = sum(item.status == "success" for item in auto)
    exact_rate = exact_count / case_count
    invariant_rate = success_count / case_count
    hard_failures = case_count - success_count

    advantages: dict[str, float | None] = {}
    comparison_counts: dict[str, int] = {}
    for baseline in ("vtracer", "potrace"):
        native_nodes = 0
        baseline_nodes = 0
        comparisons = 0
        for item in auto:
            other = by_key.get((item.case_id, baseline))
            if (
                item.status != "success"
                or not item.exact_topology
                or item.premultiplied_rgba_rmse is None
                or item.node_count is None
                or other is None
                or other.status != "success"
                or not other.exact_topology
                or other.premultiplied_rgba_rmse is None
                or other.node_count is None
                or item.premultiplied_rgba_rmse > other.premultiplied_rgba_rmse + fidelity_band
            ):
                continue
            native_nodes += item.node_count
            baseline_nodes += other.node_count
            comparisons += 1
        comparison_counts[baseline] = comparisons
        advantages[baseline] = (
            1.0 - native_nodes / baseline_nodes if comparisons > 0 and baseline_nodes > 0 else None
        )

    no_subpixel_deltas: list[float] = []
    bezier_node_deltas: list[float] = []
    for item in auto:
        no_subpixel = by_key.get((item.case_id, "engine-no-subpixel"))
        bezier = by_key.get((item.case_id, "engine-bezier-only"))
        if (
            item.premultiplied_rgba_rmse is not None
            and no_subpixel is not None
            and no_subpixel.premultiplied_rgba_rmse is not None
        ):
            no_subpixel_deltas.append(
                no_subpixel.premultiplied_rgba_rmse - item.premultiplied_rgba_rmse
            )
        if item.node_count is not None and bezier is not None and bezier.node_count is not None:
            bezier_node_deltas.append(bezier.node_count - item.node_count)

    minimum_comparisons = math.ceil(case_count * 0.5)
    node_advantage = any(
        advantage is not None
        and advantage > 0.0
        and comparison_counts[baseline] >= minimum_comparisons
        for baseline, advantage in advantages.items()
    )
    criteria = {
        "exact_topology_at_least_95_percent": exact_rate >= 0.95,
        "shared_boundary_hard_fail_rate_zero": hard_failures == 0,
        "node_advantage_in_fidelity_band": node_advantage,
        "no_subpixel_ablation_reported": bool(no_subpixel_deltas),
        "bezier_only_ablation_reported": bool(bezier_node_deltas),
    }
    return GateEvaluation(
        passed=all(criteria.values()),
        exact_topology_rate=exact_rate,
        shared_boundary_invariant_rate=invariant_rate,
        hard_failure_count=hard_failures,
        baseline_node_advantage=advantages,
        baseline_comparison_count=comparison_counts,
        no_subpixel_rmse_delta=_mean(no_subpixel_deltas),
        bezier_only_node_delta=_mean(bezier_node_deltas),
        criteria=criteria,
    )


def run_e2_gate(
    output_directory: Path,
    *,
    native_executable: Path,
    resvg_executable: Path,
    vtracer: VTracerAdapter,
    potrace: PotraceAdapter,
    renderer: ResvgAdapter,
    case_count: int = 20,
) -> GateEvaluation:
    if output_directory.exists():
        raise E2GateError(f"output directory already exists: {output_directory}")
    output_directory.mkdir(parents=True)
    cases = generate_e2_cases(output_directory / "dataset", count=case_count)
    measurements: list[E2Measurement] = []
    for case in cases:
        case_output = output_directory / "runs" / case.case_id
        measurements.append(
            _run_engine(
                case,
                case_output / "engine-auto",
                native_executable=native_executable,
                resvg_executable=resvg_executable,
                runner="engine-auto",
                subpixel=True,
                bezier_only=False,
            )
        )
        measurements.append(
            _run_engine(
                case,
                case_output / "engine-no-subpixel",
                native_executable=native_executable,
                resvg_executable=resvg_executable,
                runner="engine-no-subpixel",
                subpixel=False,
                bezier_only=False,
            )
        )
        measurements.append(
            _run_engine(
                case,
                case_output / "engine-bezier-only",
                native_executable=native_executable,
                resvg_executable=resvg_executable,
                runner="engine-bezier-only",
                subpixel=True,
                bezier_only=True,
            )
        )
        measurements.extend(
            _run_baselines(
                case,
                case_output / "baselines",
                vtracer=vtracer,
                potrace=potrace,
                renderer=renderer,
            )
        )
    evaluation = evaluate_g1(measurements, case_count=len(cases))
    semantic_measurements = [
        {key: value for key, value in asdict(item).items() if key != "wall_time_ms"}
        for item in measurements
    ]
    semantic_digest = hashlib.sha256(
        json.dumps(semantic_measurements, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    report = {
        "schema_version": E2_GATE_SCHEMA_VERSION,
        "dataset_id": "procedural-e2-binary-v1",
        "case_count": len(cases),
        "semantic_digest": semantic_digest,
        "evaluation": asdict(evaluation),
        "measurements": [asdict(item) for item in measurements],
    }
    report_path = output_directory / "e2-g1-report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    if not evaluation.passed:
        (output_directory / "GATE_FAILED").write_text(
            "Gate G1 did not pass; inspect e2-g1-report.json.\n", encoding="utf-8"
        )
    return evaluation
