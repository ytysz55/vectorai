from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from vectorai_bench.fixtures import generate_fixture_set
from vectorai_engine.decode import decode_bytes
from vectorai_engine.errors import EngineFailure
from vectorai_engine.normalize import normalize_source
from vectorai_engine.palette import (
    PaletteConfig,
    generate_palette_hypotheses,
    symmetric_palette_error,
)
from vectorai_engine.reliability import analyze_reliability


def stripe_image(colors: list[tuple[int, int, int]]) -> Image.Image:
    width = len(colors) * 12
    image = Image.new("RGB", (width, 18))
    pixels = image.load()
    assert pixels is not None
    for color_index, color in enumerate(colors):
        for y in range(image.height):
            for x in range(color_index * 12, (color_index + 1) * 12):
                pixels[x, y] = color
    return image


def normalized(image: Image.Image):  # type: ignore[no-untyped-def]
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return normalize_source(decode_bytes(buffer.getvalue()))


@pytest.mark.parametrize("color_count", [2, 3, 4, 6, 8, 10, 12])
def test_recovers_exact_palette_count_and_colors(color_count: int) -> None:
    colors = [
        (
            (37 * index + 17) % 256,
            (83 * index + 29) % 256,
            (149 * index + 53) % 256,
        )
        for index in range(color_count)
    ]
    source = normalized(stripe_image(colors))
    result = generate_palette_hypotheses(source, analyze_reliability(source))
    assert result.selected.color_count == color_count
    assert result.selected.labels.shape == (18, color_count * 12)
    assert not result.selected.labels.flags.writeable
    expected = tuple((red / 255.0, green / 255.0, blue / 255.0) for red, green, blue in colors)
    assert symmetric_palette_error(result.selected.colors, expected) < 1.0e-6
    assert set(np.unique(result.selected.labels).tolist()) == set(range(color_count))


def test_transparent_pixels_do_not_create_palette_entries() -> None:
    image = Image.new("RGBA", (20, 10), (255, 0, 255, 0))
    for x in range(10):
        for y in range(10):
            image.putpixel((x, y), (255, 0, 0, 255))
    for x in range(10, 20):
        for y in range(10):
            image.putpixel((x, y), (0, 0, 255, 255))
    image.putpixel((0, 0), (0, 255, 0, 0))
    source = normalized(image)
    result = generate_palette_hypotheses(source)
    assert result.selected.color_count == 2
    assert result.active_pixel_count == 199
    assert int(result.selected.labels[0, 0]) == -1


def test_antialiased_transparent_fixtures_use_design_colors_only(tmp_path: Path) -> None:
    manifest = generate_fixture_set(tmp_path)
    expected = {
        "synthetic-circle-001": 1,
        "synthetic-ring-001": 1,
        "synthetic-text-like-001": 1,
        "synthetic-junction-001": 3,
        "synthetic-nested-001": 3,
        "synthetic-shared-edge-001": 2,
    }
    for case in manifest.cases:
        color_count = expected.get(case.family_id)
        if color_count is None or case.raster_asset is None:
            continue
        payload = (tmp_path / case.raster_asset.artifact_ref).read_bytes()
        source = normalize_source(decode_bytes(payload))
        result = generate_palette_hypotheses(source, analyze_reliability(source))
        assert result.selected.color_count == color_count
        assert int(np.count_nonzero(result.selected.labels >= 0)) == result.active_pixel_count


def test_invalid_palette_bounds_are_typed() -> None:
    source = normalized(stripe_image([(255, 0, 0), (0, 0, 255)]))
    with pytest.raises(EngineFailure):
        generate_palette_hypotheses(source, config=PaletteConfig(maximum_colors=13))
