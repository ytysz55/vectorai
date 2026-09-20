"""Deterministic reliability evidence for binary boundary reconstruction."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from .normalize import NormalizedImage


@dataclass(frozen=True, slots=True, eq=False)
class ReliabilityMap:
    confidence: NDArray[np.float32]
    edge_strength: NDArray[np.float32]
    blur_uncertainty: NDArray[np.float32]
    jpeg_block_penalty: NDArray[np.float32]
    alpha_uncertainty: NDArray[np.float32]
    low_contrast_penalty: NDArray[np.float32]


def _normalize(values: NDArray[np.float32]) -> NDArray[np.float32]:
    try:
        maximum = float(np.max(values))
    except (TypeError, ValueError, FloatingPointError) as error:
        raise ValueError(f"cannot normalize reliability channel: {error}") from error
    if maximum <= 1e-8:
        return np.zeros_like(values, dtype=np.float32)
    return (values / maximum).astype(np.float32)


def _gradient(values: NDArray[np.float32]) -> tuple[NDArray[np.float32], NDArray[np.float32]]:
    padded = np.pad(values, 1, mode="edge")
    gradient_x = (padded[1:-1, 2:] - padded[1:-1, :-2]) * 0.5
    gradient_y = (padded[2:, 1:-1] - padded[:-2, 1:-1]) * 0.5
    return gradient_x.astype(np.float32), gradient_y.astype(np.float32)


def analyze_reliability(image: NormalizedImage) -> ReliabilityMap:
    evidence = image.foreground_evidence
    gradient_x, gradient_y = _gradient(evidence)
    magnitude = np.sqrt(gradient_x * gradient_x + gradient_y * gradient_y).astype(np.float32)
    edge_strength = _normalize(magnitude)

    padded = np.pad(evidence, 1, mode="edge")
    laplacian = np.abs(
        padded[1:-1, :-2] + padded[1:-1, 2:] + padded[:-2, 1:-1] + padded[2:, 1:-1] - 4.0 * evidence
    ).astype(np.float32)
    sharpness = _normalize(laplacian)
    blur_uncertainty = (edge_strength * (1.0 - sharpness)).astype(np.float32)

    block_penalty = np.zeros_like(evidence, dtype=np.float32)
    if image.width > 8:
        for column in range(8, image.width, 8):
            difference = np.abs(evidence[:, column] - evidence[:, column - 1])
            block_penalty[:, max(0, column - 1) : min(image.width, column + 1)] += difference[
                :, None
            ]
    if image.height > 8:
        for row in range(8, image.height, 8):
            difference = np.abs(evidence[row, :] - evidence[row - 1, :])
            block_penalty[max(0, row - 1) : min(image.height, row + 1), :] += difference[None, :]
    jpeg_block_penalty = _normalize(block_penalty)

    alpha = image.rgba_srgb[..., 3]
    alpha_uncertainty = (4.0 * alpha * (1.0 - alpha)).astype(np.float32)
    low_contrast_penalty = (1.0 - edge_strength).astype(np.float32)
    uncertainty = (
        0.30 * blur_uncertainty
        + 0.25 * jpeg_block_penalty
        + 0.25 * alpha_uncertainty
        + 0.20 * low_contrast_penalty
    )
    confidence = np.clip(1.0 - uncertainty, 0.0, 1.0).astype(np.float32)

    arrays = (
        confidence,
        edge_strength,
        blur_uncertainty,
        jpeg_block_penalty,
        alpha_uncertainty,
        low_contrast_penalty,
    )
    if not all(np.isfinite(array).all() for array in arrays):
        raise ValueError("reliability analysis produced non-finite values")
    for array in arrays:
        array.setflags(write=False)
    return ReliabilityMap(*arrays)
