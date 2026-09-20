"""Dependency-free, versioned benchmark dataset contracts."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import cast

type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]

_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
_STABLE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class ManifestValidationError(ValueError):
    """Raised when an in-memory dataset manifest violates its contract."""


class Split(StrEnum):
    DEVELOPMENT = "development"
    VALIDATION = "validation"
    LOCKED_TEST = "locked_test"


class PrimaryClass(StrEnum):
    LOGO = "logo"
    ICON = "icon"
    TURKISH_TEXT = "turkish_text"
    JPEG_BLUR = "jpeg_blur"
    ALPHA = "alpha"
    LINE_ART = "line_art"


class VariantTier(StrEnum):
    T0 = "T0"
    T1 = "T1"
    T2 = "T2"
    T3 = "T3"


def _ensure_stable_id(value: str, path: str) -> None:
    if not _STABLE_ID_RE.fullmatch(value):
        raise ManifestValidationError(f"{path} is not a stable identifier")


def _mapping(value: object, path: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ManifestValidationError(f"{path} must be an object")
    return cast(dict[str, object], value)


def _sequence(value: object, path: str) -> list[object]:
    if not isinstance(value, list):
        raise ManifestValidationError(f"{path} must be an array")
    return cast(list[object], value)


def _string(value: object, path: str) -> str:
    if not isinstance(value, str) or not value:
        raise ManifestValidationError(f"{path} must be a non-empty string")
    return value


def _integer(value: object, path: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ManifestValidationError(f"{path} must be an integer >= {minimum}")
    return value


def _number(value: object, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ManifestValidationError(f"{path} must be a number")
    try:
        return float(value)
    except (TypeError, ValueError, OverflowError) as error:
        raise ManifestValidationError(f"{path} cannot be converted to float") from error


def _json_value(value: object, path: str) -> JsonValue:
    if value is None or isinstance(value, str | bool | int | float):
        return value
    if isinstance(value, list):
        return [_json_value(item, f"{path}[]") for item in value]
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        mapping = cast(dict[str, object], value)
        return {key: _json_value(item, f"{path}.{key}") for key, item in mapping.items()}
    raise ManifestValidationError(f"{path} must contain only JSON values")


def _enum_value[T: StrEnum](enum_type: type[T], value: object, path: str) -> T:
    raw = _string(value, path)
    try:
        return enum_type(raw)
    except ValueError as error:
        choices = ", ".join(item.value for item in enum_type)
        raise ManifestValidationError(f"{path} must be one of: {choices}") from error


@dataclass(frozen=True, slots=True)
class SourceAsset:
    sha256: str
    media_type: str
    artifact_ref: str
    provenance: str
    license_id: str

    def __post_init__(self) -> None:
        if not _SHA256_RE.fullmatch(self.sha256):
            raise ManifestValidationError("source asset sha256 must be lowercase hexadecimal")
        for field_name in ("media_type", "artifact_ref", "provenance", "license_id"):
            if not getattr(self, field_name):
                raise ManifestValidationError(f"source asset {field_name} cannot be empty")

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "sha256": self.sha256,
            "media_type": self.media_type,
            "artifact_ref": self.artifact_ref,
            "provenance": self.provenance,
            "license_id": self.license_id,
        }


@dataclass(frozen=True, slots=True)
class Point:
    x: float
    y: float

    def to_dict(self) -> dict[str, JsonValue]:
        return {"x": self.x, "y": self.y}


@dataclass(frozen=True, slots=True)
class TopologyTruth:
    components: int
    holes: int
    adjacency: tuple[tuple[int, int], ...] = ()
    junction_degrees: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        if self.components < 0 or self.holes < 0:
            raise ManifestValidationError("topology counts cannot be negative")
        canonical = tuple(
            sorted((min(left, right), max(left, right)) for left, right in self.adjacency)
        )
        if any(left == right for left, right in canonical):
            raise ManifestValidationError("adjacency cannot contain self edges")
        if len(set(canonical)) != len(canonical):
            raise ManifestValidationError("adjacency cannot contain duplicate edges")
        if self.adjacency != canonical:
            raise ManifestValidationError("adjacency edges must be sorted and canonical")
        if any(degree < 1 for degree in self.junction_degrees):
            raise ManifestValidationError("junction degrees must be positive")

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "components": self.components,
            "holes": self.holes,
            "adjacency": [list(edge) for edge in self.adjacency],
            "junction_degrees": list(self.junction_degrees),
        }


@dataclass(frozen=True, slots=True)
class GeometryTruth:
    contours: tuple[tuple[Point, ...], ...] = ()
    corners: tuple[Point, ...] = ()
    primitive_types: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "contours": [[point.to_dict() for point in contour] for contour in self.contours],
            "corners": [point.to_dict() for point in self.corners],
            "primitive_types": list(self.primitive_types),
        }


@dataclass(frozen=True, slots=True)
class GroundTruth:
    topology: TopologyTruth
    geometry: GeometryTruth = field(default_factory=GeometryTruth)
    vector_asset: SourceAsset | None = None

    def to_dict(self) -> dict[str, JsonValue]:
        payload: dict[str, JsonValue] = {
            "topology": self.topology.to_dict(),
            "geometry": self.geometry.to_dict(),
        }
        if self.vector_asset is not None:
            payload["vector_asset"] = self.vector_asset.to_dict()
        return payload


@dataclass(frozen=True, slots=True)
class DesignFamily:
    family_id: str
    split: Split
    primary_class: PrimaryClass
    source: SourceAsset
    ground_truth: GroundTruth
    tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _ensure_stable_id(self.family_id, "family_id")
        if any(not tag for tag in self.tags):
            raise ManifestValidationError("tags cannot contain empty values")
        if tuple(sorted(set(self.tags))) != self.tags:
            raise ManifestValidationError("tags must be unique and sorted")

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "family_id": self.family_id,
            "split": self.split.value,
            "primary_class": self.primary_class.value,
            "tags": list(self.tags),
            "source": self.source.to_dict(),
            "ground_truth": self.ground_truth.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class Variant:
    tier: VariantTier
    seed: int
    width: int
    height: int
    parameters: dict[str, JsonValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.seed < 0 or self.width < 1 or self.height < 1:
            raise ManifestValidationError("variant seed and dimensions are out of range")

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "tier": self.tier.value,
            "seed": self.seed,
            "width": self.width,
            "height": self.height,
            "parameters": self.parameters,
        }


@dataclass(frozen=True, slots=True)
class BenchmarkCase:
    case_id: str
    family_id: str
    variant: Variant
    raster_asset: SourceAsset | None = None

    def __post_init__(self) -> None:
        _ensure_stable_id(self.case_id, "case_id")
        _ensure_stable_id(self.family_id, "family_id")

    def to_dict(self) -> dict[str, JsonValue]:
        payload: dict[str, JsonValue] = {
            "case_id": self.case_id,
            "family_id": self.family_id,
            "variant": self.variant.to_dict(),
        }
        if self.raster_asset is not None:
            payload["raster_asset"] = self.raster_asset.to_dict()
        return payload


@dataclass(frozen=True, slots=True)
class DatasetManifest:
    schema_version: str
    dataset_id: str
    families: tuple[DesignFamily, ...]
    cases: tuple[BenchmarkCase, ...]

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", self.schema_version):
            raise ManifestValidationError("schema_version must use semantic version syntax")
        _ensure_stable_id(self.dataset_id, "dataset_id")

        family_ids = [family.family_id for family in self.families]
        if len(family_ids) != len(set(family_ids)):
            raise ManifestValidationError("family_id values must be unique")
        case_ids = [case.case_id for case in self.cases]
        if len(case_ids) != len(set(case_ids)):
            raise ManifestValidationError("case_id values must be unique")

        missing = sorted({case.family_id for case in self.cases} - set(family_ids))
        if missing:
            raise ManifestValidationError(f"cases reference unknown families: {missing}")
        if family_ids != sorted(family_ids):
            raise ManifestValidationError("families must be sorted by family_id")
        if case_ids != sorted(case_ids):
            raise ManifestValidationError("cases must be sorted by case_id")

    @classmethod
    def model_validate(cls, payload: object) -> DatasetManifest:
        root = _mapping(payload, "manifest")
        families = tuple(
            _parse_family(item, f"families[{index}]")
            for index, item in enumerate(_sequence(root.get("families"), "families"))
        )
        cases = tuple(
            _parse_case(item, f"cases[{index}]")
            for index, item in enumerate(_sequence(root.get("cases"), "cases"))
        )
        return cls(
            schema_version=_string(root.get("schema_version"), "schema_version"),
            dataset_id=_string(root.get("dataset_id"), "dataset_id"),
            families=families,
            cases=cases,
        )

    def model_dump(self, *, mode: str = "json", exclude_none: bool = True) -> dict[str, JsonValue]:
        if mode != "json":
            raise ValueError("only JSON model dumps are supported")
        del exclude_none
        return {
            "schema_version": self.schema_version,
            "dataset_id": self.dataset_id,
            "families": [family.to_dict() for family in self.families],
            "cases": [case.to_dict() for case in self.cases],
        }


def _parse_source(value: object, path: str) -> SourceAsset:
    item = _mapping(value, path)
    return SourceAsset(
        sha256=_string(item.get("sha256"), f"{path}.sha256"),
        media_type=_string(item.get("media_type"), f"{path}.media_type"),
        artifact_ref=_string(item.get("artifact_ref"), f"{path}.artifact_ref"),
        provenance=_string(item.get("provenance"), f"{path}.provenance"),
        license_id=_string(item.get("license_id"), f"{path}.license_id"),
    )


def _parse_point(value: object, path: str) -> Point:
    item = _mapping(value, path)
    return Point(x=_number(item.get("x"), f"{path}.x"), y=_number(item.get("y"), f"{path}.y"))


def _parse_topology(value: object, path: str) -> TopologyTruth:
    item = _mapping(value, path)
    adjacency: list[tuple[int, int]] = []
    for index, raw_edge in enumerate(_sequence(item.get("adjacency", []), f"{path}.adjacency")):
        edge = _sequence(raw_edge, f"{path}.adjacency[{index}]")
        if len(edge) != 2:
            raise ManifestValidationError(f"{path}.adjacency[{index}] must have two endpoints")
        adjacency.append(
            (
                _integer(edge[0], f"{path}.adjacency[{index}][0]"),
                _integer(edge[1], f"{path}.adjacency[{index}][1]"),
            )
        )
    junctions = tuple(
        _integer(value, f"{path}.junction_degrees[]", minimum=1)
        for value in _sequence(item.get("junction_degrees", []), f"{path}.junction_degrees")
    )
    return TopologyTruth(
        components=_integer(item.get("components"), f"{path}.components"),
        holes=_integer(item.get("holes"), f"{path}.holes"),
        adjacency=tuple(adjacency),
        junction_degrees=junctions,
    )


def _parse_geometry(value: object, path: str) -> GeometryTruth:
    item = _mapping(value, path)
    contours = tuple(
        tuple(
            _parse_point(point, f"{path}.contours[{contour_index}][{point_index}]")
            for point_index, point in enumerate(
                _sequence(contour, f"{path}.contours[{contour_index}]")
            )
        )
        for contour_index, contour in enumerate(
            _sequence(item.get("contours", []), f"{path}.contours")
        )
    )
    corners = tuple(
        _parse_point(point, f"{path}.corners[{index}]")
        for index, point in enumerate(_sequence(item.get("corners", []), f"{path}.corners"))
    )
    primitives = tuple(
        _string(value, f"{path}.primitive_types[]")
        for value in _sequence(item.get("primitive_types", []), f"{path}.primitive_types")
    )
    return GeometryTruth(contours=contours, corners=corners, primitive_types=primitives)


def _parse_ground_truth(value: object, path: str) -> GroundTruth:
    item = _mapping(value, path)
    vector_value = item.get("vector_asset")
    return GroundTruth(
        topology=_parse_topology(item.get("topology"), f"{path}.topology"),
        geometry=_parse_geometry(item.get("geometry", {}), f"{path}.geometry"),
        vector_asset=(
            None if vector_value is None else _parse_source(vector_value, f"{path}.vector_asset")
        ),
    )


def _parse_family(value: object, path: str) -> DesignFamily:
    item = _mapping(value, path)
    tags = tuple(
        _string(value, f"{path}.tags[]")
        for value in _sequence(item.get("tags", []), f"{path}.tags")
    )
    return DesignFamily(
        family_id=_string(item.get("family_id"), f"{path}.family_id"),
        split=_enum_value(Split, item.get("split"), f"{path}.split"),
        primary_class=_enum_value(PrimaryClass, item.get("primary_class"), f"{path}.primary_class"),
        tags=tags,
        source=_parse_source(item.get("source"), f"{path}.source"),
        ground_truth=_parse_ground_truth(item.get("ground_truth"), f"{path}.ground_truth"),
    )


def _parse_variant(value: object, path: str) -> Variant:
    item = _mapping(value, path)
    raw_parameters = _mapping(item.get("parameters", {}), f"{path}.parameters")
    parameters = {
        key: _json_value(value, f"{path}.parameters.{key}") for key, value in raw_parameters.items()
    }
    return Variant(
        tier=_enum_value(VariantTier, item.get("tier"), f"{path}.tier"),
        seed=_integer(item.get("seed"), f"{path}.seed"),
        width=_integer(item.get("width"), f"{path}.width", minimum=1),
        height=_integer(item.get("height"), f"{path}.height", minimum=1),
        parameters=parameters,
    )


def _parse_case(value: object, path: str) -> BenchmarkCase:
    item = _mapping(value, path)
    raster_value = item.get("raster_asset")
    return BenchmarkCase(
        case_id=_string(item.get("case_id"), f"{path}.case_id"),
        family_id=_string(item.get("family_id"), f"{path}.family_id"),
        variant=_parse_variant(item.get("variant"), f"{path}.variant"),
        raster_asset=(
            None if raster_value is None else _parse_source(raster_value, f"{path}.raster_asset")
        ),
    )
