"""Deterministic SVG structure and editability metrics."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass
from pathlib import Path

METRIC_VERSION = "1.0.0"
MAX_SVG_BYTES = 16 * 1024 * 1024
_PATH_TOKEN = re.compile(r"[AaCcHhLlMmQqSsTtVvZz]|[-+]?(?:\d+\.?(?:\d*)?|\.\d+)(?:[eE][-+]?\d+)?")
_COMMAND_ARITY = {
    "M": 2,
    "L": 2,
    "H": 1,
    "V": 1,
    "C": 6,
    "S": 4,
    "Q": 4,
    "T": 2,
    "A": 7,
    "Z": 0,
}
_PRIMITIVES = frozenset({"rect", "circle", "ellipse", "line", "polyline", "polygon"})
_ALLOWED = _PRIMITIVES | frozenset(
    {"svg", "g", "defs", "clipPath", "mask", "path", "title", "desc"}
)
_KNOWN_SVG_10_DOCTYPE = re.compile(
    rb'<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 20010904//EN"\s+'
    rb'"http://www\.w3\.org/TR/2001/REC-SVG-20010904/DTD/svg10\.dtd">'
)


@dataclass(frozen=True, slots=True)
class EditabilityMetrics:
    metric_version: str
    path_count: int
    primitive_count: int
    segment_count: int
    node_count: int
    group_count: int
    unsupported_element_count: int


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _path_complexity(path_data: str) -> tuple[int, int]:
    tokens = _PATH_TOKEN.findall(path_data.replace(",", " "))
    index = 0
    command: str | None = None
    nodes = 0
    segments = 0
    first_group = True
    while index < len(tokens):
        token = tokens[index]
        if token.isalpha():
            command = token.upper()
            index += 1
            first_group = True
            if command == "Z":
                segments += 1
                command = None
            continue
        if command is None:
            raise ValueError("path data contains coordinates without a command")
        arity = _COMMAND_ARITY[command]
        if arity == 0 or index + arity > len(tokens):
            raise ValueError("path data has an incomplete command")
        if any(part.isalpha() for part in tokens[index : index + arity]):
            raise ValueError("path data has an incomplete command")
        index += arity
        if command == "M" and first_group:
            nodes += 1
        else:
            nodes += 1
            segments += 1
        first_group = False
    return nodes, segments


def _point_count(value: str) -> int:
    try:
        numbers = [float(item) for item in _PATH_TOKEN.findall(value) if not item.isalpha()]
    except ValueError as error:
        raise ValueError(f"primitive points contain an invalid number: {error}") from error
    if len(numbers) % 2:
        raise ValueError("primitive points must contain coordinate pairs")
    return len(numbers) // 2


def _primitive_complexity(name: str, attributes: dict[str, str]) -> tuple[int, int]:
    if name in {"rect", "circle", "ellipse"}:
        return 4, 4
    if name == "line":
        return 2, 1
    points = _point_count(attributes.get("points", ""))
    if name == "polyline":
        return points, max(points - 1, 0)
    if name == "polygon":
        return points, points if points > 1 else 0
    return 0, 0


def measure_svg_editability(
    svg_path: Path, *, allow_known_svg_10_doctype: bool = False
) -> EditabilityMetrics:
    try:
        if svg_path.stat().st_size > MAX_SVG_BYTES:
            raise ValueError(f"SVG exceeds {MAX_SVG_BYTES} bytes")
        payload = svg_path.read_bytes()
    except OSError as error:
        raise ValueError(f"cannot read SVG {svg_path}: {error}") from error
    upper = payload.upper()
    if b"<!ENTITY" in upper:
        raise ValueError("XML entities are forbidden")
    if b"<!DOCTYPE" in upper:
        if not allow_known_svg_10_doctype or _KNOWN_SVG_10_DOCTYPE.search(payload) is None:
            raise ValueError("unknown XML document type is forbidden")
        payload = _KNOWN_SVG_10_DOCTYPE.sub(b"", payload, count=1)
    try:
        root = ElementTree.fromstring(payload)
    except ElementTree.ParseError as error:
        raise ValueError(f"invalid SVG XML: {error}") from error

    path_count = primitive_count = segment_count = node_count = group_count = unsupported = 0
    for element in root.iter():
        name = _local_name(element.tag)
        if name == "path":
            path_count += 1
            nodes, segments = _path_complexity(element.attrib.get("d", ""))
            node_count += nodes
            segment_count += segments
        elif name in _PRIMITIVES:
            primitive_count += 1
            nodes, segments = _primitive_complexity(name, element.attrib)
            node_count += nodes
            segment_count += segments
        elif name == "g":
            group_count += 1
        elif name not in _ALLOWED:
            unsupported += 1

    return EditabilityMetrics(
        metric_version=METRIC_VERSION,
        path_count=path_count,
        primitive_count=primitive_count,
        segment_count=segment_count,
        node_count=node_count,
        group_count=group_count,
        unsupported_element_count=unsupported,
    )
