from __future__ import annotations

import io

import numpy as np
from PIL import Image

from vectorai_engine.decode import decode_bytes
from vectorai_engine.normalize import normalize_source
from vectorai_engine.palette import PaletteConfig, generate_palette_hypotheses
from vectorai_engine.reliability import analyze_reliability
from vectorai_engine.segmentation import segment_multicolor


def encode(image: Image.Image, format_name: str = "PNG", **kwargs: object) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format=format_name, **kwargs)
    return buffer.getvalue()


def normalized(payload: bytes):  # type: ignore[no-untyped-def]
    return normalize_source(decode_bytes(payload))


def three_stripes() -> Image.Image:
    image = Image.new("RGB", (ninety := 90, 36))
    colors = ((220, 30, 40), (20, 180, 90), (30, 70, 220))
    for index, color in enumerate(colors):
        for x in range(index * (ninety // 3), (index + 1) * (ninety // 3)):
            for y in range(image.height):
                image.putpixel((x, y), color)
    return image


def test_jpeg_variation_does_not_fragment_three_regions() -> None:
    clean = normalized(encode(three_stripes()))
    palette = generate_palette_hypotheses(
        clean,
        analyze_reliability(clean),
        PaletteConfig(minimum_colors=3, maximum_colors=3),
    ).selected
    jpeg = normalized(encode(three_stripes(), "JPEG", quality=24, subsampling=2))
    first = segment_multicolor(jpeg, palette, analyze_reliability(jpeg))
    second = segment_multicolor(jpeg, palette, analyze_reliability(jpeg))
    assert len(first.regions) == 3
    assert np.array_equal(first.labels, second.labels)
    expected = [int(palette.labels[18, x]) for x in (15, 45, 75)]
    assert [int(first.labels[18, x]) for x in (15, 45, 75)] == expected
    assert all(region.pixel_count > 900 for region in first.regions)
    assert first.iterations_run <= 6


def test_small_color_islands_are_removed_without_palette_count_change() -> None:
    image = Image.new("RGB", (64, 32), (240, 30, 30))
    for x in range(32, 64):
        for y in range(32):
            image.putpixel((x, y), (20, 40, 230))
    clean = normalized(encode(image))
    palette = generate_palette_hypotheses(
        clean,
        config=PaletteConfig(minimum_colors=2, maximum_colors=2),
    ).selected
    noisy = image.copy()
    for index in range(20):
        x = (index * 13) % 30 + 1
        y = (index * 7) % 30 + 1
        noisy.putpixel((x, y), (20, 40, 230))
    source = normalized(encode(noisy))
    result = segment_multicolor(source, palette, analyze_reliability(source))
    assert len(result.regions) == 2
    assert {region.palette_index for region in result.regions} == {0, 1}


def test_transparent_pixels_remain_inactive() -> None:
    image = Image.new("RGBA", (20, 12), (0, 255, 0, 0))
    for x in range(2, 9):
        for y in range(2, 10):
            image.putpixel((x, y), (255, 0, 0, 255))
    for x in range(11, 18):
        for y in range(2, 10):
            image.putpixel((x, y), (0, 0, 255, 255))
    source = normalized(encode(image))
    palette = generate_palette_hypotheses(source).selected
    result = segment_multicolor(source, palette, analyze_reliability(source))
    assert int(result.labels[0, 0]) == -1
    assert float(result.confidence[0, 0]) == 0.0
    assert len(result.regions) == 2
    assert not result.labels.flags.writeable
    assert not result.confidence.flags.writeable
