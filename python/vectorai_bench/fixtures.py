"""Deterministic procedural ground-truth fixtures for benchmark calibration."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw

from .manifest import write_manifest
from .models import (
    BenchmarkCase,
    DatasetManifest,
    DesignFamily,
    GeometryTruth,
    GroundTruth,
    Point,
    PrimaryClass,
    SourceAsset,
    Split,
    TopologyTruth,
    Variant,
    VariantTier,
)

CANVAS_SIZE = 256
ANTIALIAS_SCALE = 4
PROVENANCE = "VectorAI procedural fixture generator v1"
SYNTHETIC_LICENSE = "LicenseRef-VectorAI-Synthetic"
DrawFunction = Callable[[Image.Image, int], None]


@dataclass(frozen=True, slots=True)
class FixtureDefinition:
    family_id: str
    split: Split
    primary_class: PrimaryClass
    tags: tuple[str, ...]
    svg_body: str
    topology: TopologyTruth
    geometry: GeometryTruth
    draw: DrawFunction


def _box(values: tuple[int, int, int, int], scale: int) -> tuple[int, int, int, int]:
    return tuple(value * scale for value in values)  # type: ignore[return-value]


def _points(values: tuple[tuple[int, int], ...], scale: int) -> list[tuple[int, int]]:
    return [(x * scale, y * scale) for x, y in values]


def _draw_circle(image: Image.Image, scale: int) -> None:
    ImageDraw.Draw(image).ellipse(_box((40, 40, 216, 216), scale), fill="#2563eb")


def _draw_ring(image: Image.Image, scale: int) -> None:
    draw = ImageDraw.Draw(image)
    draw.ellipse(_box((28, 28, 228, 228), scale), fill="#7c3aed")
    draw.ellipse(_box((82, 82, 174, 174), scale), fill=(0, 0, 0, 0))


def _draw_nested(image: Image.Image, scale: int) -> None:
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(_box((24, 24, 232, 232), scale), radius=24 * scale, fill="#fbbf24")
    draw.ellipse(_box((58, 58, 198, 198), scale), fill="#ef4444")
    draw.rectangle(_box((102, 102, 154, 154), scale), fill="#1d4ed8")


def _draw_line_art(image: Image.Image, scale: int) -> None:
    draw = ImageDraw.Draw(image)
    draw.line(
        _points(((32, 192), (88, 64), (128, 160), (176, 48), (224, 192)), scale),
        fill="#111827",
        width=12 * scale,
        joint="curve",
    )


def _draw_shared_edge(image: Image.Image, scale: int) -> None:
    draw = ImageDraw.Draw(image)
    draw.rectangle(_box((24, 48, 128, 208), scale), fill="#0ea5e9")
    draw.rectangle(_box((128, 48, 232, 208), scale), fill="#f97316")


def _draw_junction(image: Image.Image, scale: int) -> None:
    draw = ImageDraw.Draw(image)
    center = (128, 128)
    draw.polygon(_points(((24, 24), (232, 24), center), scale), fill="#ec4899")
    draw.polygon(_points(((232, 24), (232, 232), center), scale), fill="#14b8a6")
    draw.polygon(_points(((232, 232), (24, 232), (24, 24), center), scale), fill="#8b5cf6")


def _draw_text_like(image: Image.Image, scale: int) -> None:
    draw = ImageDraw.Draw(image)
    draw.rectangle(_box((36, 56, 72, 212), scale), fill="#111827")
    draw.ellipse(_box((36, 20, 72, 48), scale), fill="#111827")
    draw.rectangle(_box((104, 44, 136, 212), scale), fill="#111827")
    draw.rectangle(_box((136, 44, 214, 76), scale), fill="#111827")
    draw.rectangle(_box((136, 112, 198, 144), scale), fill="#111827")
    draw.ellipse(_box((138, 178, 178, 218), scale), fill="#111827")
    draw.ellipse(_box((148, 188, 168, 208), scale), fill=(0, 0, 0, 0))


def _rect_contour(left: int, top: int, right: int, bottom: int) -> tuple[Point, ...]:
    return (
        Point(left, top),
        Point(right, top),
        Point(right, bottom),
        Point(left, bottom),
    )


def fixture_definitions() -> tuple[FixtureDefinition, ...]:
    return (
        FixtureDefinition(
            family_id="synthetic-circle-001",
            split=Split.DEVELOPMENT,
            primary_class=PrimaryClass.ICON,
            tags=("circle", "primitive", "synthetic"),
            svg_body='<circle cx="128" cy="128" r="88" fill="#2563eb"/>',
            topology=TopologyTruth(components=1, holes=0),
            geometry=GeometryTruth(primitive_types=("circle",)),
            draw=_draw_circle,
        ),
        FixtureDefinition(
            family_id="synthetic-junction-001",
            split=Split.VALIDATION,
            primary_class=PrimaryClass.ICON,
            tags=("junction", "shared-boundary", "synthetic"),
            svg_body=(
                '<path d="M24 24H232L128 128Z" fill="#ec4899"/>'
                '<path d="M232 24V232L128 128Z" fill="#14b8a6"/>'
                '<path d="M232 232H24V24L128 128Z" fill="#8b5cf6"/>'
            ),
            topology=TopologyTruth(
                components=3,
                holes=0,
                adjacency=((0, 1), (0, 2), (1, 2)),
                junction_degrees=(3,),
            ),
            geometry=GeometryTruth(corners=(Point(128.0, 128.0),)),
            draw=_draw_junction,
        ),
        FixtureDefinition(
            family_id="synthetic-line-art-001",
            split=Split.DEVELOPMENT,
            primary_class=PrimaryClass.LINE_ART,
            tags=("line-art", "stroke", "synthetic"),
            svg_body=(
                '<path d="M32 192L88 64L128 160L176 48L224 192" fill="none" '
                'stroke="#111827" stroke-width="12" stroke-linecap="round" '
                'stroke-linejoin="round"/>'
            ),
            topology=TopologyTruth(components=1, holes=0),
            geometry=GeometryTruth(
                corners=(
                    Point(88.0, 64.0),
                    Point(128.0, 160.0),
                    Point(176.0, 48.0),
                ),
                primitive_types=("polyline-stroke",),
            ),
            draw=_draw_line_art,
        ),
        FixtureDefinition(
            family_id="synthetic-nested-001",
            split=Split.DEVELOPMENT,
            primary_class=PrimaryClass.LOGO,
            tags=("multicolor", "nested", "synthetic"),
            svg_body=(
                '<rect x="24" y="24" width="208" height="208" rx="24" fill="#fbbf24"/>'
                '<circle cx="128" cy="128" r="70" fill="#ef4444"/>'
                '<rect x="102" y="102" width="52" height="52" fill="#1d4ed8"/>'
            ),
            topology=TopologyTruth(components=3, holes=0, adjacency=((0, 1), (1, 2))),
            geometry=GeometryTruth(primitive_types=("rounded-rect", "circle", "rect")),
            draw=_draw_nested,
        ),
        FixtureDefinition(
            family_id="synthetic-ring-001",
            split=Split.DEVELOPMENT,
            primary_class=PrimaryClass.ICON,
            tags=("hole", "primitive", "synthetic"),
            svg_body=(
                '<path fill="#7c3aed" fill-rule="evenodd" '
                'd="M128 28A100 100 0 1 1 127.999 28Z '
                'M128 82A46 46 0 1 0 128.001 82Z"/>'
            ),
            topology=TopologyTruth(components=1, holes=1),
            geometry=GeometryTruth(primitive_types=("circle", "circle")),
            draw=_draw_ring,
        ),
        FixtureDefinition(
            family_id="synthetic-shared-edge-001",
            split=Split.DEVELOPMENT,
            primary_class=PrimaryClass.LOGO,
            tags=("multicolor", "shared-boundary", "synthetic"),
            svg_body=(
                '<rect x="24" y="48" width="104" height="160" fill="#0ea5e9"/>'
                '<rect x="128" y="48" width="104" height="160" fill="#f97316"/>'
            ),
            topology=TopologyTruth(components=2, holes=0, adjacency=((0, 1),)),
            geometry=GeometryTruth(
                contours=(
                    _rect_contour(24, 48, 128, 208),
                    _rect_contour(128, 48, 232, 208),
                ),
                corners=(Point(128.0, 48.0), Point(128.0, 208.0)),
                primitive_types=("rect", "rect"),
            ),
            draw=_draw_shared_edge,
        ),
        FixtureDefinition(
            family_id="synthetic-text-like-001",
            split=Split.LOCKED_TEST,
            primary_class=PrimaryClass.TURKISH_TEXT,
            tags=("synthetic", "text-like", "turkish"),
            svg_body=(
                '<g fill="#111827">'
                '<rect x="36" y="56" width="36" height="156"/>'
                '<ellipse cx="54" cy="34" rx="18" ry="14"/>'
                '<rect x="104" y="44" width="32" height="168"/>'
                '<rect x="136" y="44" width="78" height="32"/>'
                '<rect x="136" y="112" width="62" height="32"/>'
                '<path fill-rule="evenodd" '
                'd="M158 178A20 20 0 1 1 157.999 178Z M158 188A10 10 0 1 0 158.001 188Z"/>'
                "</g>"
            ),
            topology=TopologyTruth(components=3, holes=1),
            geometry=GeometryTruth(primitive_types=("rect", "ellipse", "rect", "ring")),
            draw=_draw_text_like,
        ),
    )


def _svg_document(body: str) -> bytes:
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256" '
        f'viewBox="0 0 {CANVAS_SIZE} {CANVAS_SIZE}">{body}</svg>\n'
    )
    return svg.encode()


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _render_reference(definition: FixtureDefinition) -> Image.Image:
    size = CANVAS_SIZE * ANTIALIAS_SCALE
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    definition.draw(image, ANTIALIAS_SCALE)
    return image.resize((CANVAS_SIZE, CANVAS_SIZE), Image.Resampling.LANCZOS)


def generate_fixture_set(output_dir: Path) -> DatasetManifest:
    families: list[DesignFamily] = []
    cases: list[BenchmarkCase] = []

    for definition in fixture_definitions():
        fixture_dir = output_dir / "fixtures" / definition.family_id
        fixture_dir.mkdir(parents=True, exist_ok=True)

        svg_bytes = _svg_document(definition.svg_body)
        svg_path = fixture_dir / "ground-truth.svg"
        svg_path.write_bytes(svg_bytes)

        png_path = fixture_dir / "reference.png"
        _render_reference(definition).save(png_path, format="PNG", optimize=False, compress_level=9)
        png_bytes = png_path.read_bytes()

        svg_asset = SourceAsset(
            sha256=_sha256(svg_bytes),
            media_type="image/svg+xml",
            artifact_ref=f"fixtures/{definition.family_id}/ground-truth.svg",
            provenance=PROVENANCE,
            license_id=SYNTHETIC_LICENSE,
        )
        raster_asset = SourceAsset(
            sha256=_sha256(png_bytes),
            media_type="image/png",
            artifact_ref=f"fixtures/{definition.family_id}/reference.png",
            provenance=PROVENANCE,
            license_id=SYNTHETIC_LICENSE,
        )
        families.append(
            DesignFamily(
                family_id=definition.family_id,
                split=definition.split,
                primary_class=definition.primary_class,
                tags=definition.tags,
                source=svg_asset,
                ground_truth=GroundTruth(
                    topology=definition.topology,
                    geometry=definition.geometry,
                    vector_asset=svg_asset,
                ),
            )
        )
        cases.append(
            BenchmarkCase(
                case_id=f"{definition.family_id}-t0",
                family_id=definition.family_id,
                variant=Variant(
                    tier=VariantTier.T0,
                    seed=1000 + len(cases),
                    width=CANVAS_SIZE,
                    height=CANVAS_SIZE,
                    parameters={"antialias_scale": ANTIALIAS_SCALE},
                ),
                raster_asset=raster_asset,
            )
        )

    manifest = DatasetManifest(
        schema_version="1.0.0",
        dataset_id="procedural-e1-v1",
        families=tuple(sorted(families, key=lambda family: family.family_id)),
        cases=tuple(sorted(cases, key=lambda case: case.case_id)),
    )
    write_manifest(output_dir / "manifest.json", manifest)
    return manifest
