"""Canonical stroke SVG and closed cut-outline export."""

from __future__ import annotations

import math
from dataclasses import asdict
from pathlib import Path
from xml.etree import ElementTree

from vectorai_bench.metrics.editability import measure_svg_editability

from .stroke_graph import CenterlineGraph, PixelPoint, StrokeEdge
from .stroke_models import StrokeCap, StrokeStyle, WidthModel, WidthModelKind


def _number(value: float, decimals: int = 4) -> str:
    if not math.isfinite(value):
        raise ValueError("stroke coordinate is not finite")
    threshold = 0.5 * 10.0**-decimals
    normalized = 0.0 if abs(value) < threshold else value
    rendered = f"{normalized:.{decimals}f}".rstrip("0").rstrip(".")
    return "0" if rendered == "-0" else rendered


def _center(point: PixelPoint) -> tuple[float, float]:
    return point.x + 0.5, point.y + 0.5


def _distance_squared(
    point: tuple[float, float],
    start: tuple[float, float],
    end: tuple[float, float],
) -> float:
    delta_x = end[0] - start[0]
    delta_y = end[1] - start[1]
    denominator = delta_x * delta_x + delta_y * delta_y
    if denominator <= 1.0e-12:
        return (point[0] - start[0]) ** 2 + (point[1] - start[1]) ** 2
    projection = ((point[0] - start[0]) * delta_x + (point[1] - start[1]) * delta_y) / denominator
    projection = min(1.0, max(0.0, projection))
    closest = (start[0] + projection * delta_x, start[1] + projection * delta_y)
    return (point[0] - closest[0]) ** 2 + (point[1] - closest[1]) ** 2


def _simplify(
    points: tuple[tuple[float, float], ...],
    tolerance: float = 1.5,
) -> tuple[tuple[float, float], ...]:
    if len(points) <= 2:
        return points
    keep = {0, len(points) - 1}
    pending = [(0, len(points) - 1)]
    threshold = tolerance * tolerance
    while pending:
        start, end = pending.pop()
        maximum = -1.0
        selected = -1
        for index in range(start + 1, end):
            distance = _distance_squared(points[index], points[start], points[end])
            if distance > maximum:
                maximum = distance
                selected = index
        if selected >= 0 and maximum > threshold:
            keep.add(selected)
            pending.extend(((start, selected), (selected, end)))
    return tuple(points[index] for index in sorted(keep))


def _unit(vector_x: float, vector_y: float) -> tuple[float, float]:
    length = math.hypot(vector_x, vector_y)
    if length <= 1.0e-9:
        return 1.0, 0.0
    return vector_x / length, vector_y / length


def _edge_points(
    graph: CenterlineGraph,
    edge: StrokeEdge,
    width: float,
    cap: StrokeCap,
) -> tuple[tuple[float, float], ...]:
    points = list(_simplify(tuple(_center(point) for point in edge.points)))
    if len(points) < 2:
        raise ValueError("stroke edge has fewer than two points")
    extension_factor = (
        0.5 if cap is StrokeCap.BUTT else 1.0 / 6.0 if cap is StrokeCap.ROUND else 0.0
    )
    if extension_factor > 0.0 and edge.start_node != edge.end_node:
        start_node = graph.nodes[edge.start_node]
        end_node = graph.nodes[edge.end_node]
        if start_node.degree == 1:
            direction = _unit(points[0][0] - points[1][0], points[0][1] - points[1][1])
            points[0] = (
                points[0][0] + extension_factor * width * direction[0],
                points[0][1] + extension_factor * width * direction[1],
            )
        if end_node.degree == 1:
            direction = _unit(points[-1][0] - points[-2][0], points[-1][1] - points[-2][1])
            points[-1] = (
                points[-1][0] + extension_factor * width * direction[0],
                points[-1][1] + extension_factor * width * direction[1],
            )
    return tuple(points)


def _path_data(points: tuple[tuple[float, float], ...], *, closed: bool) -> str:
    pieces = [f"M{_number(points[0][0])} {_number(points[0][1])}"]
    pieces.extend(f"L{_number(x)} {_number(y)}" for x, y in points[1:])
    if closed:
        pieces.append("Z")
    return " ".join(pieces)


def _point_widths(edge: StrokeEdge, model: WidthModel) -> tuple[float, ...]:
    widths = model.edge_widths[edge.edge_id]
    if len(widths) == len(edge.points):
        return widths
    return tuple(model.constant_width for _ in edge.points)


def _outline_polygon(
    graph: CenterlineGraph,
    edge: StrokeEdge,
    model: WidthModel,
    style: StrokeStyle,
) -> tuple[tuple[float, float], ...]:
    raw_points = tuple(_center(point) for point in edge.points)
    points = _simplify(raw_points)
    raw_widths = _point_widths(edge, model)
    width_for_point = {point: raw_widths[index] for index, point in enumerate(raw_points)}
    widths = tuple(width_for_point.get(point, model.constant_width) for point in points)
    tangents: list[tuple[float, float]] = []
    for index, point in enumerate(points):
        if index == 0:
            other = points[1]
            tangent = _unit(other[0] - point[0], other[1] - point[1])
        elif index == len(points) - 1:
            other = points[-2]
            tangent = _unit(point[0] - other[0], point[1] - other[1])
        else:
            tangent = _unit(
                points[index + 1][0] - points[index - 1][0],
                points[index + 1][1] - points[index - 1][1],
            )
        tangents.append(tangent)
    adjusted = list(points)
    if edge.start_node != edge.end_node and style.cap is StrokeCap.SQUARE:
        if graph.nodes[edge.start_node].degree == 1:
            adjusted[0] = (
                adjusted[0][0] - 0.5 * widths[0] * tangents[0][0],
                adjusted[0][1] - 0.5 * widths[0] * tangents[0][1],
            )
        if graph.nodes[edge.end_node].degree == 1:
            adjusted[-1] = (
                adjusted[-1][0] + 0.5 * widths[-1] * tangents[-1][0],
                adjusted[-1][1] + 0.5 * widths[-1] * tangents[-1][1],
            )
    left: list[tuple[float, float]] = []
    right: list[tuple[float, float]] = []
    for point, tangent, width in zip(adjusted, tangents, widths, strict=True):
        normal = (-tangent[1], tangent[0])
        radius = 0.5 * width
        left.append((point[0] + radius * normal[0], point[1] + radius * normal[1]))
        right.append((point[0] - radius * normal[0], point[1] - radius * normal[1]))
    return tuple(left + list(reversed(right)))


def export_stroke_svg(
    graph: CenterlineGraph,
    model: WidthModel,
    style: StrokeStyle,
    *,
    color: str,
    output_path: Path | None = None,
    cut_outline: bool = False,
) -> tuple[str, dict[str, object]]:
    if not color.startswith("#") or len(color) != 7:
        raise ValueError("stroke color must be canonical #rrggbb")
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{graph.width}" '
        f'height="{graph.height}" viewBox="0 0 {graph.width} {graph.height}">'
    ]
    for edge in graph.edges:
        closed = edge.start_node == edge.end_node
        if cut_outline or model.kind is WidthModelKind.VARIABLE:
            polygon = _outline_polygon(graph, edge, model, style)
            lines.append(
                f'  <path data-stroke-edge="{edge.edge_id}" fill="{color}" '
                f'stroke="none" d="{_path_data(polygon, closed=True)}"/>'
            )
        else:
            points = _edge_points(graph, edge, model.constant_width, style.cap)
            lines.append(
                f'  <path data-stroke-edge="{edge.edge_id}" fill="none" '
                f'stroke="{color}" stroke-width="{_number(model.constant_width)}" '
                f'stroke-linecap="{style.cap.value}" stroke-linejoin="{style.join.value}" '
                f'd="{_path_data(points, closed=closed)}"/>'
            )
    lines.append("</svg>")
    payload = "\n".join(lines) + "\n"
    manifest: dict[str, object] = {
        "edge_count": len(graph.edges),
        "node_count": len(graph.nodes),
        "component_count": graph.component_count,
        "width_model": model.kind.value,
        "width": model.constant_width,
        "style": asdict(style),
        "cut_outline": cut_outline,
    }
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(payload, encoding="utf-8", newline="\n")
        manifest["editability"] = asdict(measure_svg_editability(output_path))
    return payload, manifest


def validate_cut_outline(svg_path: Path) -> tuple[bool, tuple[str, ...]]:
    errors: list[str] = []
    try:
        root = ElementTree.fromstring(svg_path.read_bytes())
    except (OSError, ElementTree.ParseError) as error:
        return False, (f"invalid cut-outline SVG: {error}",)
    paths = [element for element in root.iter() if element.tag.rsplit("}", 1)[-1] == "path"]
    if not paths:
        errors.append("cut-outline has no paths")
    for path in paths:
        if path.attrib.get("stroke", "none") != "none":
            errors.append("cut-outline path has a visible stroke")
        if not path.attrib.get("d", "").strip().endswith("Z"):
            errors.append("cut-outline path is not closed")
    return not errors, tuple(errors)
