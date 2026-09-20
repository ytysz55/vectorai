from __future__ import annotations

import io

import numpy as np
from PIL import Image, ImageDraw

from vectorai_engine.decode import decode_bytes
from vectorai_engine.normalize import normalize_source
from vectorai_engine.reliability import analyze_reliability


def encoded(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def normalized(image: Image.Image):  # type: ignore[no-untyped-def]
    return normalize_source(decode_bytes(encoded(image)))


def test_transparent_image_uses_alpha_as_foreground_evidence() -> None:
    image = Image.new("RGBA", (8, 8), (255, 255, 255, 0))
    ImageDraw.Draw(image).rectangle((2, 2, 5, 5), fill=(255, 255, 255, 255))
    result = normalized(image)
    assert np.all(result.foreground_evidence[2:6, 2:6] == 1.0)
    assert np.all(result.foreground_evidence[:2, :] == 0.0)
    assert "FOREGROUND_FROM_ALPHA" in result.warnings


def test_opaque_polarity_uses_border_color_for_black_or_white_shapes() -> None:
    black_on_white = Image.new("RGB", (10, 10), "white")
    ImageDraw.Draw(black_on_white).rectangle((3, 3, 6, 6), fill="black")
    white_on_black = Image.new("RGB", (10, 10), "black")
    ImageDraw.Draw(white_on_black).rectangle((3, 3, 6, 6), fill="white")
    first = normalized(black_on_white)
    second = normalized(white_on_black)
    assert first.foreground_evidence[4, 4] > 0.99
    assert first.foreground_evidence[0, 0] < 0.01
    assert second.foreground_evidence[4, 4] > 0.99
    assert second.foreground_evidence[0, 0] < 0.01


def test_linear_rgba_oklab_and_reliability_are_finite_and_bounded() -> None:
    image = Image.new("RGBA", (24, 16), (0, 0, 0, 0))
    ImageDraw.Draw(image).ellipse((4, 2, 19, 13), fill=(124, 58, 237, 200))
    result = normalized(image)
    reliability = analyze_reliability(result)
    assert result.rgba_linear.shape == (16, 24, 4)
    assert result.oklab.shape == (16, 24, 3)
    assert not result.rgba_linear.flags.writeable
    for channel in (
        reliability.confidence,
        reliability.edge_strength,
        reliability.blur_uncertainty,
        reliability.jpeg_block_penalty,
        reliability.alpha_uncertainty,
        reliability.low_contrast_penalty,
    ):
        assert channel.shape == (16, 24)
        assert np.isfinite(channel).all()
        assert float(channel.min()) >= 0.0
        assert float(channel.max()) <= 1.0
        assert not channel.flags.writeable


def test_uniform_opaque_image_is_explicitly_flagged() -> None:
    result = normalized(Image.new("RGB", (5, 5), "gray"))
    assert "UNIFORM_OPAQUE_IMAGE" in result.warnings
    assert np.count_nonzero(result.foreground_evidence) == 0
