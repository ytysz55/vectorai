"""Resource-bounded PNG/JPEG decoding and source metadata normalization."""

from __future__ import annotations

import hashlib
import io
import warnings
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from numpy.typing import NDArray
from PIL import Image, ImageCms, ImageOps, UnidentifiedImageError

from .errors import EngineError, EngineFailure, ErrorCode, Stage

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
JPEG_SIGNATURE = b"\xff\xd8\xff"
SUPPORTED_MEDIA_TYPES = frozenset({"image/png", "image/jpeg"})


@dataclass(frozen=True, slots=True)
class DecodeLimits:
    max_input_bytes: int = 32 * 1024 * 1024
    max_width: int = 8192
    max_height: int = 8192
    max_pixels: int = 16_777_216
    max_decoded_bytes: int = 256 * 1024 * 1024

    def __post_init__(self) -> None:
        if (
            min(
                self.max_input_bytes,
                self.max_width,
                self.max_height,
                self.max_pixels,
                self.max_decoded_bytes,
            )
            < 1
        ):
            raise ValueError("decode limits must be positive")


@dataclass(frozen=True, slots=True, eq=False)
class SourceImage:
    width: int
    height: int
    rgba: NDArray[np.uint8]
    media_type: str
    format_name: str
    source_sha256: str
    icc_profile_sha256: str | None
    orientation_applied: bool
    source_was_premultiplied: bool
    warnings: tuple[str, ...]


def _failure(
    code: ErrorCode,
    message: str,
    *,
    context: dict[str, str] | None = None,
) -> EngineFailure:
    return EngineFailure(
        EngineError(
            code=code,
            stage=Stage.DECODE,
            message=message,
            context={} if context is None else context,
        )
    )


def _sniff_media_type(payload: bytes) -> str | None:
    if payload.startswith(PNG_SIGNATURE):
        return "image/png"
    if payload.startswith(JPEG_SIGNATURE):
        return "image/jpeg"
    return None


def _check_dimensions(width: int, height: int, limits: DecodeLimits) -> None:
    pixels = width * height
    decoded_bytes = pixels * 4
    if (
        width < 1
        or height < 1
        or width > limits.max_width
        or height > limits.max_height
        or pixels > limits.max_pixels
        or decoded_bytes > limits.max_decoded_bytes
    ):
        raise _failure(
            ErrorCode.RESOURCE_LIMIT,
            "decoded image exceeds configured dimensions or memory budget",
            context={
                "width": str(width),
                "height": str(height),
                "pixels": str(pixels),
                "decoded_bytes": str(decoded_bytes),
            },
        )


def _convert_icc_to_srgb(image: Image.Image, icc_profile: bytes) -> Image.Image:
    try:
        source_profile = ImageCms.ImageCmsProfile(io.BytesIO(icc_profile))
        target_profile = ImageCms.createProfile("sRGB")
        alpha = image.getchannel("A") if "A" in image.getbands() else None
        converted = ImageCms.profileToProfile(
            image.convert("RGB"),
            source_profile,
            target_profile,
            outputMode="RGB",
        )
        if converted is None:
            raise ValueError("ICC transform returned no image")
        if alpha is not None:
            converted.putalpha(alpha)
        return converted
    except (OSError, TypeError, ValueError, ImageCms.PyCMSError) as error:
        raise _failure(
            ErrorCode.INVALID_COLOR_PROFILE,
            f"cannot convert embedded ICC profile to sRGB: {error}",
        ) from error


def decode_bytes(
    payload: bytes,
    *,
    media_type: str | None = None,
    limits: DecodeLimits | None = None,
) -> SourceImage:
    active_limits = DecodeLimits() if limits is None else limits
    if not payload:
        raise _failure(ErrorCode.DECODE_ERROR, "input raster is empty")
    if len(payload) > active_limits.max_input_bytes:
        raise _failure(
            ErrorCode.RESOURCE_LIMIT,
            "compressed raster exceeds input byte budget",
            context={"input_bytes": str(len(payload))},
        )

    detected_media_type = _sniff_media_type(payload)
    if detected_media_type is None:
        raise _failure(ErrorCode.UNSUPPORTED_INPUT, "only PNG and JPEG inputs are supported")
    if media_type is not None:
        if media_type not in SUPPORTED_MEDIA_TYPES:
            raise _failure(
                ErrorCode.UNSUPPORTED_INPUT,
                f"unsupported declared media type: {media_type}",
            )
        if media_type != detected_media_type:
            raise _failure(
                ErrorCode.DECODE_ERROR,
                "declared media type does not match raster signature",
            )

    source_digest = hashlib.sha256(payload).hexdigest()
    decode_warnings: list[str] = []
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(payload)) as opened:
                expected_format = "PNG" if detected_media_type == "image/png" else "JPEG"
                if opened.format != expected_format:
                    raise _failure(
                        ErrorCode.DECODE_ERROR,
                        f"decoder format mismatch: expected {expected_format}, got {opened.format}",
                    )
                _check_dimensions(opened.width, opened.height, active_limits)
                orientation = opened.getexif().get(274, 1)
                premultiplied = opened.mode in {"RGBa", "La"}
                opened.load()
                oriented = ImageOps.exif_transpose(opened)
                _check_dimensions(oriented.width, oriented.height, active_limits)
                icc_value = oriented.info.get("icc_profile")
                if isinstance(icc_value, bytes) and icc_value:
                    color_managed = _convert_icc_to_srgb(oriented, icc_value)
                    icc_digest = hashlib.sha256(icc_value).hexdigest()
                else:
                    color_managed = oriented
                    icc_digest = None
                    decode_warnings.append("ASSUMED_SRGB_NO_ICC")
                rgba_image = color_managed.convert("RGBA")
                rgba = np.asarray(rgba_image, dtype=np.uint8).copy()
    except EngineFailure:
        raise
    except (Image.DecompressionBombWarning, Image.DecompressionBombError) as error:
        raise _failure(ErrorCode.RESOURCE_LIMIT, f"decompression bomb rejected: {error}") from error
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as error:
        raise _failure(ErrorCode.DECODE_ERROR, f"cannot decode raster: {error}") from error

    rgba.setflags(write=False)
    return SourceImage(
        width=rgba.shape[1],
        height=rgba.shape[0],
        rgba=rgba,
        media_type=detected_media_type,
        format_name="PNG" if detected_media_type == "image/png" else "JPEG",
        source_sha256=source_digest,
        icc_profile_sha256=icc_digest,
        orientation_applied=orientation not in {0, 1},
        source_was_premultiplied=premultiplied,
        warnings=tuple(decode_warnings),
    )


def decode_path(
    path: Path,
    *,
    media_type: str | None = None,
    limits: DecodeLimits | None = None,
) -> SourceImage:
    active_limits = DecodeLimits() if limits is None else limits
    try:
        size = path.stat().st_size
        if size > active_limits.max_input_bytes:
            raise _failure(
                ErrorCode.RESOURCE_LIMIT,
                "compressed raster exceeds input byte budget",
                context={"input_bytes": str(size)},
            )
        payload = path.read_bytes()
    except EngineFailure:
        raise
    except OSError as error:
        raise _failure(ErrorCode.DECODE_ERROR, f"cannot read raster {path}: {error}") from error
    return decode_bytes(payload, media_type=media_type, limits=active_limits)
