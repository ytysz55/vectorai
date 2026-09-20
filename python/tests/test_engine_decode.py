from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from vectorai_engine.decode import DecodeLimits, decode_bytes, decode_path
from vectorai_engine.errors import EngineFailure, ErrorCode


def encode(image: Image.Image, format_name: str, **kwargs: object) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format=format_name, **kwargs)
    return buffer.getvalue()


def test_png_and_jpeg_decode_to_straight_rgba() -> None:
    png = encode(Image.new("RGBA", (7, 5), (10, 20, 30, 128)), "PNG")
    jpeg = encode(Image.new("RGB", (6, 4), (200, 100, 50)), "JPEG", quality=90)
    decoded_png = decode_bytes(png, media_type="image/png")
    decoded_jpeg = decode_bytes(jpeg, media_type="image/jpeg")
    assert decoded_png.rgba.shape == (5, 7, 4)
    assert decoded_png.rgba.dtype == np.uint8
    assert int(decoded_png.rgba[0, 0, 3]) == 128
    assert decoded_jpeg.rgba.shape == (4, 6, 4)
    assert np.all(decoded_jpeg.rgba[..., 3] == 255)
    assert not decoded_png.rgba.flags.writeable
    assert "ASSUMED_SRGB_NO_ICC" in decoded_png.warnings


def test_exif_orientation_is_applied() -> None:
    image = Image.new("RGB", (4, 2), "white")
    exif = Image.Exif()
    exif[274] = 6
    payload = encode(image, "JPEG", exif=exif)
    decoded = decode_bytes(payload)
    assert (decoded.width, decoded.height) == (2, 4)
    assert decoded.orientation_applied


def test_signature_mismatch_and_corruption_are_typed() -> None:
    png = encode(Image.new("RGB", (2, 2), "black"), "PNG")
    with pytest.raises(EngineFailure) as mismatch:
        decode_bytes(png, media_type="image/jpeg")
    assert mismatch.value.error.code is ErrorCode.DECODE_ERROR

    with pytest.raises(EngineFailure) as unsupported:
        decode_bytes(b"not an image")
    assert unsupported.value.error.code is ErrorCode.UNSUPPORTED_INPUT

    with pytest.raises(EngineFailure) as corrupt:
        decode_bytes(png[:20])
    assert corrupt.value.error.code is ErrorCode.DECODE_ERROR


def test_resource_limits_reject_bytes_dimensions_and_path(tmp_path: Path) -> None:
    payload = encode(Image.new("RGBA", (8, 8), "red"), "PNG")
    with pytest.raises(EngineFailure) as byte_limit:
        decode_bytes(payload, limits=DecodeLimits(max_input_bytes=8))
    assert byte_limit.value.error.code is ErrorCode.RESOURCE_LIMIT

    with pytest.raises(EngineFailure) as dimension_limit:
        decode_bytes(payload, limits=DecodeLimits(max_width=4))
    assert dimension_limit.value.error.code is ErrorCode.RESOURCE_LIMIT

    path = tmp_path / "input.png"
    path.write_bytes(payload)
    with pytest.raises(EngineFailure) as path_limit:
        decode_path(path, limits=DecodeLimits(max_input_bytes=8))
    assert path_limit.value.error.code is ErrorCode.RESOURCE_LIMIT


def test_invalid_icc_profile_is_rejected() -> None:
    payload = encode(
        Image.new("RGB", (4, 4), "blue"),
        "PNG",
        icc_profile=b"not-an-icc-profile",
    )
    with pytest.raises(EngineFailure) as failure:
        decode_bytes(payload)
    assert failure.value.error.code is ErrorCode.INVALID_COLOR_PROFILE
