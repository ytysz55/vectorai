"""Straight-alpha sRGB, linear RGBA, OKLab, and binary foreground evidence."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from .decode import SourceImage
from .errors import EngineError, EngineFailure, ErrorCode, Stage


@dataclass(frozen=True, slots=True, eq=False)
class NormalizedImage:
    width: int
    height: int
    rgba_srgb: NDArray[np.float32]
    rgba_linear: NDArray[np.float32]
    oklab: NDArray[np.float32]
    foreground_evidence: NDArray[np.float32]
    background_rgb_srgb: tuple[float, float, float]
    warnings: tuple[str, ...]


def srgb_to_linear(values: NDArray[np.float32]) -> NDArray[np.float32]:
    converted = np.where(
        values <= 0.04045,
        values / 12.92,
        ((values + 0.055) / 1.055) ** 2.4,
    )
    return converted.astype(np.float32, copy=False)


def linear_rgb_to_oklab(rgb: NDArray[np.float32]) -> NDArray[np.float32]:
    red = rgb[..., 0]
    green = rgb[..., 1]
    blue = rgb[..., 2]
    l_value = 0.4122214708 * red + 0.5363325363 * green + 0.0514459929 * blue
    m_value = 0.2119034982 * red + 0.6806995451 * green + 0.1073969566 * blue
    s_value = 0.0883024619 * red + 0.2817188376 * green + 0.6299787005 * blue
    l_root = np.cbrt(np.clip(l_value, 0.0, None))
    m_root = np.cbrt(np.clip(m_value, 0.0, None))
    s_root = np.cbrt(np.clip(s_value, 0.0, None))
    return np.stack(
        (
            0.2104542553 * l_root + 0.7936177850 * m_root - 0.0040720468 * s_root,
            1.9779984951 * l_root - 2.4285922050 * m_root + 0.4505937099 * s_root,
            0.0259040371 * l_root + 0.7827717662 * m_root - 0.8086757660 * s_root,
        ),
        axis=-1,
    ).astype(np.float32, copy=False)


def _border_pixels(rgb: NDArray[np.float32]) -> NDArray[np.float32]:
    if rgb.shape[0] == 1 or rgb.shape[1] == 1:
        return rgb.reshape(-1, 3)
    return np.concatenate(
        (rgb[0, :, :], rgb[-1, :, :], rgb[1:-1, 0, :], rgb[1:-1, -1, :]),
        axis=0,
    )


def normalize_source(source: SourceImage) -> NormalizedImage:
    srgb = source.rgba.astype(np.float32) / 255.0
    alpha = srgb[..., 3:4]
    linear_rgb = srgb_to_linear(srgb[..., :3])
    rgba_linear = np.concatenate((linear_rgb, alpha), axis=2).astype(np.float32)
    oklab = linear_rgb_to_oklab(linear_rgb)

    border = _border_pixels(srgb[..., :3])
    background = np.median(border, axis=0).astype(np.float32)
    alpha_has_transparency = bool(np.min(alpha) < 0.999)
    normalize_warnings = list(source.warnings)
    if alpha_has_transparency:
        evidence = alpha[..., 0]
        normalize_warnings.append("FOREGROUND_FROM_ALPHA")
    else:
        background_linear = srgb_to_linear(background.reshape(1, 1, 3))[0, 0]
        distance = np.linalg.norm(linear_rgb - background_linear, axis=2)
        try:
            maximum = float(np.max(distance))
        except (TypeError, ValueError, FloatingPointError) as error:
            raise EngineFailure(
                EngineError(
                    ErrorCode.INTERNAL_INVARIANT_VIOLATION,
                    Stage.NORMALIZE,
                    f"cannot normalize foreground distance: {error}",
                )
            ) from error
        if maximum <= 1e-7:
            evidence = np.zeros((source.height, source.width), dtype=np.float32)
            normalize_warnings.append("UNIFORM_OPAQUE_IMAGE")
        else:
            evidence = (distance / maximum).astype(np.float32)

    if not (
        np.isfinite(srgb).all()
        and np.isfinite(rgba_linear).all()
        and np.isfinite(oklab).all()
        and np.isfinite(evidence).all()
    ):
        raise EngineFailure(
            EngineError(
                ErrorCode.INTERNAL_INVARIANT_VIOLATION,
                Stage.NORMALIZE,
                "normalization produced non-finite values",
            )
        )

    for array in (srgb, rgba_linear, oklab, evidence):
        array.setflags(write=False)
    try:
        background_tuple = (
            float(background[0]),
            float(background[1]),
            float(background[2]),
        )
    except (TypeError, ValueError, OverflowError) as error:
        raise EngineFailure(
            EngineError(
                ErrorCode.INTERNAL_INVARIANT_VIOLATION,
                Stage.NORMALIZE,
                f"cannot serialize background color: {error}",
            )
        ) from error
    return NormalizedImage(
        width=source.width,
        height=source.height,
        rgba_srgb=srgb,
        rgba_linear=rgba_linear,
        oklab=oklab,
        foreground_evidence=evidence,
        background_rgb_srgb=background_tuple,
        warnings=tuple(normalize_warnings),
    )
