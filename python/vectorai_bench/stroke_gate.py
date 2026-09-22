"""Locked synthetic Stroke Gate G3 corpus, measurements, and evaluation."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from itertools import pairwise
from pathlib import Path
from typing import Any, cast

import numpy as np

from vectorai_engine.decode import decode_path
from vectorai_engine.normalize import normalize_source
from vectorai_engine.stroke_pipeline import StrokePipelineConfig, run_stroke_pipeline
from vectorai_engine.stroke_routing import RouteKind, classify_fill_stroke

from .external_tools import ToolStatus
from .renderers import ResvgAdapter


@dataclass(frozen=True, slots=True)
class StrokeTruth:
    expected_route: RouteKind
    centerlines: tuple[tuple[tuple[float, float], ...], ...] = ()
    width: float | None = None
    cap: str | None = None
    join: str | None = None
    junction_valences: tuple[int, ...] = ()
    variable_width: bool = False


@dataclass(frozen=True, slots=True)
class StrokeCase:
    case_id: str
    source_path: Path
    truth: StrokeTruth


@dataclass(frozen=True, slots=True)
class StrokeMeasurement:
    case_id: str
    status: str
    route_expected: str
    route_actual: str | None
    route_correct: bool
    connectivity_exact: bool | None
    junction_exact: bool | None
    centerline_p95: float | None
    width_error: float | None
    width_model: str | None
    cap_exact: bool | None
    join_exact: bool | None
    stroke_rmse: float | None
    fill_rmse: float | None
    stroke_nodes: int | None
    fill_nodes: int | None
    selected_kind: str | None
    cut_outline_valid: bool | None
    message: str = ""


@dataclass(frozen=True, slots=True)
class StrokeGateEvaluation:
    passed: bool
    routing_accuracy: float
    connectivity_accuracy: float
    junction_accuracy: float
    maximum_centerline_p95: float | None
    mean_width_error: float | None
    style_accuracy: float
    fidelity_band_rate: float
    node_advantage_vs_fill: float | None
    cut_outline_rate: float
    hard_failure_count: int
    criteria: dict[str, bool]


def _reference_svg(width: int, height: int, body: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">\n{body}\n</svg>\n'
    )


def _render_reference(
    root: Path,
    renderer: ResvgAdapter,
    case_id: str,
    body: str,
    *,
    width: int = 128,
    height: int = 128,
) -> Path:
    case_directory = root / case_id
    case_directory.mkdir(parents=True, exist_ok=True)
    svg_path = case_directory / "reference.svg"
    png_path = case_directory / "source.png"
    svg_path.write_text(_reference_svg(width, height, body), encoding="utf-8", newline="\n")
    rendered = renderer.render(svg_path, png_path, width=width, height=height)
    if rendered.status is not ToolStatus.SUCCESS:
        raise RuntimeError(rendered.message or f"cannot render stroke fixture {case_id}")
    return png_path


def generate_stroke_cases(root: Path, renderer: ResvgAdapter) -> tuple[StrokeCase, ...]:
    if root.exists():
        raise ValueError(f"stroke fixture directory already exists: {root}")
    root.mkdir(parents=True)
    cases: list[StrokeCase] = []
    color = "#111827"
    for cap in ("butt", "round", "square"):
        case_id = f"stroke-line-{cap}"
        source = _render_reference(
            root,
            renderer,
            case_id,
            f'  <path d="M24 64 L104 64" fill="none" stroke="{color}" '
            f'stroke-width="9" stroke-linecap="{cap}" stroke-linejoin="miter"/>',
        )
        cases.append(
            StrokeCase(
                case_id,
                source,
                StrokeTruth(
                    RouteKind.STROKE,
                    (((24.0, 64.0), (104.0, 64.0)),),
                    9.0,
                    cap,
                ),
            )
        )
    for join in ("miter", "round", "bevel"):
        case_id = f"stroke-join-{join}"
        source = _render_reference(
            root,
            renderer,
            case_id,
            f'  <path d="M24 104 L64 24 L104 104" fill="none" stroke="{color}" '
            f'stroke-width="9" stroke-linecap="butt" stroke-linejoin="{join}"/>',
        )
        cases.append(
            StrokeCase(
                case_id,
                source,
                StrokeTruth(
                    RouteKind.STROKE,
                    (((24.0, 104.0), (64.0, 24.0), (104.0, 104.0)),),
                    9.0,
                    "butt",
                    join,
                ),
            )
        )
    topology_fixtures = (
        (
            "stroke-junction-t",
            (
                f'  <path d="M24 44 L104 44 M64 44 L64 108" fill="none" '
                f'stroke="{color}" stroke-width="9" stroke-linecap="round" '
                'stroke-linejoin="round"/>'
            ),
            (((24.0, 44.0), (104.0, 44.0)), ((64.0, 44.0), (64.0, 108.0))),
            (3,),
        ),
        (
            "stroke-junction-x",
            (
                f'  <path d="M20 64 L108 64 M64 20 L64 108" fill="none" '
                f'stroke="{color}" stroke-width="9" stroke-linecap="round" '
                'stroke-linejoin="round"/>'
            ),
            (((20.0, 64.0), (108.0, 64.0)), ((64.0, 20.0), (64.0, 108.0))),
            (4,),
        ),
    )
    for case_id, body, centerlines, valences in topology_fixtures:
        source = _render_reference(root, renderer, case_id, body)
        cases.append(
            StrokeCase(
                case_id,
                source,
                StrokeTruth(
                    RouteKind.STROKE,
                    centerlines,
                    9.0,
                    "round",
                    "round",
                    valences,
                ),
            )
        )
    variable_source = _render_reference(
        root,
        renderer,
        "stroke-variable-width",
        f'  <path d="M20 60 L108 53 L108 75 L20 68 Z" fill="{color}" stroke="none"/>',
    )
    cases.append(
        StrokeCase(
            "stroke-variable-width",
            variable_source,
            StrokeTruth(
                RouteKind.STROKE,
                (((20.0, 64.0), (108.0, 64.0)),),
                15.0,
                variable_width=True,
            ),
        )
    )
    fill_bodies = (
        ("fill-square", f'  <rect x="32" y="32" width="64" height="64" fill="{color}"/>'),
        ("fill-circle", f'  <circle cx="64" cy="64" r="34" fill="{color}"/>'),
        (
            "fill-logo",
            f'  <path d="M20 96 L44 24 L68 70 L88 36 L108 96 Z" fill="{color}"/>',
        ),
    )
    for case_id, body in fill_bodies:
        source = _render_reference(root, renderer, case_id, body)
        cases.append(StrokeCase(case_id, source, StrokeTruth(RouteKind.FILL)))
    ring_source = _render_reference(
        root,
        renderer,
        "fill-ring-ambiguous",
        f'  <circle cx="64" cy="64" r="34" fill="none" stroke="{color}" stroke-width="10"/>',
    )
    cases.append(
        StrokeCase(
            "fill-ring-ambiguous",
            ring_source,
            StrokeTruth(RouteKind.AMBIGUOUS),
        )
    )
    return tuple(cases)


def _mask(path: Path) -> np.ndarray[Any, np.dtype[np.bool_]]:
    normalized = normalize_source(decode_path(path))
    alpha = normalized.rgba_srgb[..., 3]
    if bool(np.any(alpha < 1.0 - 1.0e-6)):
        return np.asarray(alpha >= 0.5, dtype=np.bool_)
    return np.asarray(normalized.foreground_evidence >= 0.5, dtype=np.bool_)


def _point_segment_distance(
    point: tuple[float, float],
    start: tuple[float, float],
    end: tuple[float, float],
) -> float:
    delta_x = end[0] - start[0]
    delta_y = end[1] - start[1]
    denominator = delta_x * delta_x + delta_y * delta_y
    if denominator <= 1.0e-12:
        return math.hypot(point[0] - start[0], point[1] - start[1])
    projection = ((point[0] - start[0]) * delta_x + (point[1] - start[1]) * delta_y) / denominator
    projection = min(1.0, max(0.0, projection))
    return math.hypot(
        point[0] - (start[0] + projection * delta_x),
        point[1] - (start[1] + projection * delta_y),
    )


def _float_value(value: object, context: str) -> float:
    try:
        return float(cast(Any, value))
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError(f"cannot parse {context}: {error}") from error


def _int_value(value: object, context: str) -> int:
    try:
        return int(cast(Any, value))
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError(f"cannot parse {context}: {error}") from error


def _centerline_p95(scene: dict[str, Any], truth: StrokeTruth) -> float:
    points = [
        (
            _float_value(point["x"], "centerline x") + 0.5,
            _float_value(point["y"], "centerline y") + 0.5,
        )
        for edge in scene["graph"]["edges"]
        for point in edge["points"]
    ]
    segments = [(first, second) for line in truth.centerlines for first, second in pairwise(line)]
    if not points or not segments:
        raise ValueError("centerline metric requires predicted points and truth segments")
    distances = np.asarray(
        [min(_point_segment_distance(point, *segment) for segment in segments) for point in points],
        dtype=np.float64,
    )
    try:
        return float(np.percentile(distances, 95.0))
    except (TypeError, ValueError, FloatingPointError) as error:
        raise ValueError(f"cannot aggregate centerline p95: {error}") from error


def _route_correct(expected: RouteKind, actual: RouteKind) -> bool:
    return actual is expected


def _failed(case: StrokeCase, actual: RouteKind | None, message: str) -> StrokeMeasurement:
    return StrokeMeasurement(
        case.case_id,
        "failed",
        case.truth.expected_route.value,
        actual.value if actual is not None else None,
        actual is not None and _route_correct(case.truth.expected_route, actual),
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        message,
    )


def _style_from_candidate(candidate_id: str) -> tuple[str, str]:
    parts = candidate_id.split("-")
    if len(parts) != 3 or parts[0] != "stroke":
        raise ValueError(f"invalid stroke candidate identifier: {candidate_id}")
    return parts[1], parts[2]


def _measure_stroke_case(
    case: StrokeCase,
    output_directory: Path,
    resvg_executable: Path,
    actual_route: RouteKind,
) -> StrokeMeasurement:
    try:
        bundle = run_stroke_pipeline(
            case.source_path,
            output_directory,
            StrokePipelineConfig(resvg_executable=resvg_executable),
        )
        scene = json.loads(bundle.scene_path.read_text(encoding="utf-8"))
        manifest = json.loads(bundle.manifest_path.read_text(encoding="utf-8"))
        best_stroke_id = str(manifest["best_stroke_candidate"])
        _style_from_candidate(best_stroke_id)
        ranked = scene["arbitration"]["ranked"]
        fill = next(item for item in ranked if item["kind"] == "fill")
        stroke_candidates = [item for item in ranked if item["kind"] == "stroke"]
        stroke = next(item for item in stroke_candidates if item["candidate_id"] == best_stroke_id)
        best_style_rmse = min(
            _float_value(item["premultiplied_rgba_rmse"], "style RMSE")
            for item in stroke_candidates
        )

        def style_within_render_tolerance(*, cap: str | None, join: str | None) -> bool | None:
            expected = cap or join
            if expected is None:
                return None
            matching: list[float] = []
            for item in stroke_candidates:
                item_cap, item_join = _style_from_candidate(str(item["candidate_id"]))
                if (cap is None or item_cap == cap) and (join is None or item_join == join):
                    matching.append(_float_value(item["premultiplied_rgba_rmse"], "style RMSE"))
            return min(matching) <= best_style_rmse + 0.002 if matching else False

        valences = tuple(
            sorted(node["degree"] for node in scene["graph"]["nodes"] if node["degree"] >= 3)
        )
        width_error = (
            abs(
                _float_value(scene["width_profile"]["median_width"], "median width")
                - case.truth.width
            )
            if case.truth.width is not None
            else None
        )
        width_model = str(scene["width_model"]["kind"])
        variable_exact = not case.truth.variable_width or width_model == "variable"
        return StrokeMeasurement(
            case.case_id,
            "success",
            case.truth.expected_route.value,
            actual_route.value,
            _route_correct(case.truth.expected_route, actual_route),
            bool(stroke["exact_topology"]),
            valences == tuple(sorted(case.truth.junction_valences)),
            _centerline_p95(scene, case.truth),
            width_error,
            width_model if variable_exact else f"unexpected:{width_model}",
            style_within_render_tolerance(cap=case.truth.cap, join=None),
            style_within_render_tolerance(cap=None, join=case.truth.join),
            _float_value(stroke["premultiplied_rgba_rmse"], "stroke RMSE"),
            _float_value(fill["premultiplied_rgba_rmse"], "fill RMSE"),
            _int_value(stroke["node_count"], "stroke node count"),
            _int_value(fill["node_count"], "fill node count"),
            str(scene["arbitration"]["selected"]).split("-", 1)[0],
            bool(scene["cut_outline_valid"]),
        )
    except (OSError, RuntimeError, ValueError, KeyError, TypeError) as error:
        return _failed(case, actual_route, str(error))


def evaluate_stroke_g3(measurements: list[StrokeMeasurement]) -> StrokeGateEvaluation:
    if not measurements:
        raise ValueError("stroke G3 requires measurements")
    routing_accuracy = sum(item.route_correct for item in measurements) / len(measurements)
    stroke = [item for item in measurements if item.route_expected == RouteKind.STROKE.value]
    successful = [item for item in stroke if item.status == "success"]
    connectivity_accuracy = (
        sum(bool(item.connectivity_exact) for item in successful) / len(stroke) if stroke else 0.0
    )
    junction_items = [item for item in successful if item.junction_exact is not None]
    junction_accuracy = (
        sum(bool(item.junction_exact) for item in junction_items) / len(junction_items)
        if junction_items
        else 0.0
    )
    centerlines = [item.centerline_p95 for item in successful if item.centerline_p95 is not None]
    widths = [item.width_error for item in successful if item.width_error is not None]
    style_values = [
        value
        for item in successful
        for value in (item.cap_exact, item.join_exact)
        if value is not None
    ]
    fidelity = [
        item for item in successful if item.stroke_rmse is not None and item.fill_rmse is not None
    ]
    cut = [item.cut_outline_valid for item in successful if item.cut_outline_valid is not None]
    maximum_centerline = max(centerlines) if centerlines else None
    mean_width = sum(widths) / len(widths) if widths else None
    style_accuracy = (
        sum(bool(value) for value in style_values) / len(style_values) if style_values else 0.0
    )
    fidelity_pairs = [
        (cast(float, item.stroke_rmse), cast(float, item.fill_rmse)) for item in fidelity
    ]
    fidelity_rate = (
        sum(stroke_rmse <= fill_rmse + 0.03 for stroke_rmse, fill_rmse in fidelity_pairs)
        / len(fidelity_pairs)
        if fidelity_pairs
        else 0.0
    )
    node_pairs = [
        item for item in fidelity if item.stroke_nodes is not None and item.fill_nodes is not None
    ]
    stroke_nodes = sum(cast(int, item.stroke_nodes) for item in node_pairs)
    fill_nodes = sum(cast(int, item.fill_nodes) for item in node_pairs)
    node_advantage = 1.0 - stroke_nodes / fill_nodes if fill_nodes > 0 else None
    cut_rate = sum(bool(value) for value in cut) / len(cut) if cut else 0.0
    hard_failures = sum(item.status != "success" for item in stroke)
    criteria = {
        "routing_accuracy_at_least_90_percent": routing_accuracy >= 0.9,
        "stroke_connectivity_exact": connectivity_accuracy == 1.0,
        "junction_valence_exact": junction_accuracy == 1.0,
        "centerline_p95_at_most_2px": maximum_centerline is not None and maximum_centerline <= 2.0,
        "mean_width_error_at_most_2px": mean_width is not None and mean_width <= 2.0,
        "cap_join_accuracy_at_least_80_percent": style_accuracy >= 0.8,
        "stroke_same_fidelity_band": fidelity_rate == 1.0,
        "stroke_node_advantage_positive": node_advantage is not None and node_advantage > 0.0,
        "cut_outlines_valid": cut_rate == 1.0,
        "no_hard_failures": hard_failures == 0,
    }
    return StrokeGateEvaluation(
        passed=all(criteria.values()),
        routing_accuracy=routing_accuracy,
        connectivity_accuracy=connectivity_accuracy,
        junction_accuracy=junction_accuracy,
        maximum_centerline_p95=maximum_centerline,
        mean_width_error=mean_width,
        style_accuracy=style_accuracy,
        fidelity_band_rate=fidelity_rate,
        node_advantage_vs_fill=node_advantage,
        cut_outline_rate=cut_rate,
        hard_failure_count=hard_failures,
        criteria=criteria,
    )


def run_stroke_gate(
    output_directory: Path,
    *,
    resvg_executable: Path,
    renderer: ResvgAdapter,
) -> StrokeGateEvaluation:
    if output_directory.exists():
        raise ValueError(f"output directory already exists: {output_directory}")
    output_directory.mkdir(parents=True)
    cases = generate_stroke_cases(output_directory / "dataset", renderer)
    measurements: list[StrokeMeasurement] = []
    confusion: dict[str, dict[str, int]] = {
        expected.value: {actual.value: 0 for actual in RouteKind} for expected in RouteKind
    }
    for case in cases:
        actual: RouteKind | None = None
        try:
            decision = classify_fill_stroke(_mask(case.source_path))
            actual = decision.selected
            confusion[case.truth.expected_route.value][actual.value] += 1
            if case.truth.expected_route is RouteKind.STROKE:
                measurements.append(
                    _measure_stroke_case(
                        case,
                        output_directory / "runs" / case.case_id,
                        resvg_executable,
                        actual,
                    )
                )
            else:
                measurements.append(
                    StrokeMeasurement(
                        case.case_id,
                        "success",
                        case.truth.expected_route.value,
                        actual.value,
                        _route_correct(case.truth.expected_route, actual),
                        None,
                        None,
                        None,
                        None,
                        None,
                        None,
                        None,
                        None,
                        None,
                        None,
                        None,
                        None,
                        None,
                    )
                )
        except (OSError, RuntimeError, ValueError, TypeError) as error:
            measurements.append(_failed(case, actual, str(error)))
    evaluation = evaluate_stroke_g3(measurements)
    semantic = [
        {key: value for key, value in asdict(item).items() if key != "message"}
        for item in measurements
    ]
    report = {
        "schema_version": "1.0.0",
        "dataset_id": "procedural-e4-stroke-v1",
        "semantic_digest": hashlib.sha256(
            json.dumps(semantic, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "confusion_matrix": confusion,
        "evaluation": asdict(evaluation),
        "measurements": [asdict(item) for item in measurements],
    }
    (output_directory / "g3-report.json").write_text(
        json.dumps(report, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return evaluation
