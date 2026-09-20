"""E3 multicolor benchmark corpus and Gate G2 metric reporting."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
from PIL import Image

from vectorai_engine.multicolor_pipeline import (
    MulticolorPipelineConfig,
    run_multicolor_pipeline,
)

from .baselines import VTracerAdapter
from .external_tools import ToolStatus
from .metrics.editability import measure_svg_editability
from .metrics.fidelity import compare_rgba
from .renderers import ResvgAdapter


@dataclass(frozen=True, slots=True)
class MulticolorCase:
    case_id: str
    source_path: Path
    palette_count: int
    region_count: int
    adjacency_count: int


@dataclass(frozen=True, slots=True)
class MulticolorMeasurement:
    case_id: str
    runner: str
    status: str
    exact_topology: bool | None
    premultiplied_rgba_rmse: float | None
    node_count: int | None
    seam_gap_rate: float | None
    message: str = ""


@dataclass(frozen=True, slots=True)
class MulticolorGateEvaluation:
    passed: bool
    exact_topology_rate: float
    maximum_seam_gap_rate: float
    node_advantage_vs_vtracer: float | None
    fidelity_band_comparisons: int
    criteria: dict[str, bool]


def _palette_color(index: int) -> tuple[int, int, int]:
    return (
        (31 + 47 * index) % 224 + 16,
        (67 + 83 * index) % 224 + 16,
        (109 + 61 * index) % 224 + 16,
    )


def generate_multicolor_cases(output_directory: Path) -> tuple[MulticolorCase, ...]:
    output_directory.mkdir(parents=True, exist_ok=True)
    cases: list[MulticolorCase] = []
    for palette_count in range(2, 13):
        width = 12 * palette_count
        image = Image.new("RGB", (width, 48))
        for index in range(palette_count):
            color = _palette_color(index)
            for x in range(index * 12, (index + 1) * 12):
                for y in range(image.height):
                    image.putpixel((x, y), color)
        case_id = f"multicolor-{palette_count:02d}"
        source_path = output_directory / f"{case_id}.png"
        image.save(source_path, format="PNG", optimize=False, compress_level=9)
        cases.append(
            MulticolorCase(
                case_id,
                source_path,
                palette_count,
                palette_count,
                palette_count - 1,
            )
        )
    return tuple(cases)


def _rgba(path: Path) -> np.ndarray:
    try:
        with Image.open(path) as image:
            return np.asarray(image.convert("RGBA"), dtype=np.uint8)
    except OSError as error:
        raise RuntimeError(f"cannot read benchmark image {path}: {error}") from error


def _failed(case_id: str, runner: str, message: str) -> MulticolorMeasurement:
    return MulticolorMeasurement(case_id, runner, "failed", None, None, None, None, message)


def run_multicolor_gate(
    output_directory: Path,
    *,
    resvg_executable: Path,
    vtracer: VTracerAdapter,
    renderer: ResvgAdapter,
) -> MulticolorGateEvaluation:
    if output_directory.exists():
        raise ValueError(f"output directory already exists: {output_directory}")
    output_directory.mkdir(parents=True)
    measurements: list[MulticolorMeasurement] = []
    cases = generate_multicolor_cases(output_directory / "dataset")
    for case in cases:
        engine_output = output_directory / "runs" / case.case_id / "engine"
        try:
            bundle = run_multicolor_pipeline(
                case.source_path,
                engine_output,
                MulticolorPipelineConfig(resvg_executable=resvg_executable),
            )
            scene = json.loads(bundle.scene_path.read_text(encoding="utf-8"))
            manifest = json.loads(bundle.manifest_path.read_text(encoding="utf-8"))
            reference = _rgba(case.source_path)
            fidelity = compare_rgba(reference, _rgba(bundle.preview_path))
            topology = (
                scene["palette"]["selected_color_count"] == case.palette_count
                and scene["graph"]["face_count"] == case.region_count
                and len(scene["graph"]["adjacency"]) == case.adjacency_count
            )
            seam_gap_rate = max(
                (item["transparent_gap_rate"] for item in manifest["seams"]["observations"]),
                default=0.0,
            )
            measurements.append(
                MulticolorMeasurement(
                    case.case_id,
                    "engine",
                    "success",
                    topology,
                    fidelity.premultiplied_rgba_rmse,
                    measure_svg_editability(bundle.svg_path).node_count,
                    seam_gap_rate,
                )
            )
        except (OSError, ValueError, RuntimeError, KeyError, TypeError) as error:
            measurements.append(_failed(case.case_id, "engine", str(error)))

        baseline_output = output_directory / "runs" / case.case_id / "vtracer.svg"
        baseline = vtracer.vectorize(case.source_path, baseline_output, preset_name="faithful")
        if baseline.status is not ToolStatus.SUCCESS:
            measurements.append(
                _failed(case.case_id, "vtracer", baseline.message or baseline.status.value)
            )
            continue
        preview = baseline_output.with_suffix(".png")
        rendered = renderer.render(
            baseline_output,
            preview,
            width=case.palette_count * 12,
            height=48,
        )
        if rendered.status is not ToolStatus.SUCCESS:
            measurements.append(
                _failed(case.case_id, "vtracer", rendered.message or rendered.status.value)
            )
            continue
        try:
            fidelity = compare_rgba(_rgba(case.source_path), _rgba(preview))
            measurements.append(
                MulticolorMeasurement(
                    case.case_id,
                    "vtracer",
                    "success",
                    None,
                    fidelity.premultiplied_rgba_rmse,
                    measure_svg_editability(baseline_output).node_count,
                    None,
                )
            )
        except (OSError, ValueError, RuntimeError) as error:
            measurements.append(_failed(case.case_id, "vtracer", str(error)))

    evaluation = evaluate_multicolor_g2(
        measurements,
        case_count=len(cases),
    )
    semantic = [
        {key: value for key, value in asdict(item).items() if key != "message"}
        for item in measurements
    ]
    report = {
        "schema_version": "1.0.0",
        "dataset_id": "procedural-e3-multicolor-v1",
        "semantic_digest": hashlib.sha256(
            json.dumps(semantic, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "evaluation": asdict(evaluation),
        "measurements": [asdict(item) for item in measurements],
    }
    (output_directory / "g2-report.json").write_text(
        json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    return evaluation


def evaluate_multicolor_g2(
    measurements: list[MulticolorMeasurement], *, case_count: int, fidelity_band: float = 0.03
) -> MulticolorGateEvaluation:
    if case_count < 1 or not 0.0 <= fidelity_band <= 1.0:
        raise ValueError("case_count and fidelity_band are invalid")
    engine = [item for item in measurements if item.runner == "engine"]
    by_key = {(item.case_id, item.runner): item for item in measurements}
    exact_count = sum(item.status == "success" and bool(item.exact_topology) for item in engine)
    exact_rate = exact_count / case_count
    seam_rates = [
        item.seam_gap_rate
        for item in engine
        if item.status == "success" and item.seam_gap_rate is not None
    ]
    maximum_seam_gap = max(seam_rates, default=1.0)
    engine_nodes = 0
    baseline_nodes = 0
    comparisons = 0
    for item in engine:
        baseline = by_key.get((item.case_id, "vtracer"))
        if (
            item.status != "success"
            or item.premultiplied_rgba_rmse is None
            or item.node_count is None
            or baseline is None
            or baseline.status != "success"
            or baseline.premultiplied_rgba_rmse is None
            or baseline.node_count is None
            or item.premultiplied_rgba_rmse > baseline.premultiplied_rgba_rmse + fidelity_band
        ):
            continue
        engine_nodes += item.node_count
        baseline_nodes += baseline.node_count
        comparisons += 1
    advantage = (
        1.0 - engine_nodes / baseline_nodes if comparisons > 0 and baseline_nodes > 0 else None
    )
    criteria = {
        "topology_at_least_95_percent": exact_rate >= 0.95,
        "renderer_seams_have_no_transparent_gap": maximum_seam_gap == 0.0,
        "vtracer_fidelity_band_comparison": comparisons >= max(1, case_count // 2),
        "vtracer_node_advantage_nonnegative": advantage is not None and advantage >= 0.0,
    }
    return MulticolorGateEvaluation(
        passed=all(criteria.values()),
        exact_topology_rate=exact_rate,
        maximum_seam_gap_rate=maximum_seam_gap,
        node_advantage_vs_vtracer=advantage,
        fidelity_band_comparisons=comparisons,
        criteria=criteria,
    )
