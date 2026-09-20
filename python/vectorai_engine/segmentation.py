"""Deterministic spatial multiclass segmentation over palette hypotheses."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from .errors import EngineError, EngineFailure, ErrorCode, Stage
from .normalize import NormalizedImage
from .palette import PaletteHypothesis
from .reliability import ReliabilityMap

MAX_SEGMENTATION_PIXELS = 4_194_304


@dataclass(frozen=True, slots=True)
class SpatialSegmentationConfig:
    spatial_weight: float = 0.025
    edge_sigma: float = 0.08
    iterations: int = 6
    minimum_region_pixels: int = 3


@dataclass(frozen=True, slots=True)
class SegmentedRegion:
    region_id: int
    palette_index: int
    pixel_count: int
    bounding_box: tuple[int, int, int, int]
    touches_border: bool


@dataclass(frozen=True, slots=True)
class SpatialSegmentation:
    labels: NDArray[np.int16]
    confidence: NDArray[np.float32]
    regions: tuple[SegmentedRegion, ...]
    iterations_run: int


def _validate(
    image: NormalizedImage,
    palette: PaletteHypothesis,
    reliability: ReliabilityMap,
    config: SpatialSegmentationConfig,
) -> None:
    pixel_count = image.width * image.height
    if pixel_count < 1 or pixel_count > MAX_SEGMENTATION_PIXELS:
        raise EngineFailure(
            EngineError(
                ErrorCode.RESOURCE_LIMIT,
                Stage.SEGMENTATION,
                f"multicolor segmentation supports at most {MAX_SEGMENTATION_PIXELS} pixels",
            )
        )
    expected_shape = (image.height, image.width)
    if palette.labels.shape != expected_shape or reliability.confidence.shape != expected_shape:
        raise EngineFailure(
            EngineError(
                ErrorCode.INTERNAL_INVARIANT_VIOLATION,
                Stage.SEGMENTATION,
                "palette or reliability dimensions do not match normalized image",
            )
        )
    if (
        not np.isfinite(config.spatial_weight)
        or config.spatial_weight < 0.0
        or not np.isfinite(config.edge_sigma)
        or config.edge_sigma <= 0.0
        or config.iterations < 1
        or config.iterations > 32
        or config.minimum_region_pixels < 1
    ):
        raise EngineFailure(
            EngineError(
                ErrorCode.INTERNAL_INVARIANT_VIOLATION,
                Stage.SEGMENTATION,
                "spatial segmentation config is invalid",
            )
        )


def _label_at(labels: NDArray[np.int16], x: int, y: int) -> int:
    try:
        return int(labels[y, x])
    except (TypeError, ValueError, OverflowError, IndexError) as error:
        raise EngineFailure(
            EngineError(
                ErrorCode.INTERNAL_INVARIANT_VIOLATION,
                Stage.SEGMENTATION,
                f"cannot read segmentation label: {error}",
            )
        ) from error


def _neighbor_terms(
    lab: NDArray[np.float64], labels: NDArray[np.int16], active: NDArray[np.bool_], sigma: float
) -> tuple[list[NDArray[np.int16]], list[NDArray[np.float64]], list[NDArray[np.bool_]]]:
    neighbor_labels: list[NDArray[np.int16]] = []
    affinities: list[NDArray[np.float64]] = []
    valid_masks: list[NDArray[np.bool_]] = []
    shifts = ((-1, 0), (1, 0), (0, -1), (0, 1))
    for dy, dx in shifts:
        shifted_labels = np.roll(labels, shift=(dy, dx), axis=(0, 1))
        shifted_lab = np.roll(lab, shift=(dy, dx), axis=(0, 1))
        shifted_active = np.roll(active, shift=(dy, dx), axis=(0, 1))
        valid = active & shifted_active
        if dy == -1:
            valid[-1, :] = False
        elif dy == 1:
            valid[0, :] = False
        elif dx == -1:
            valid[:, -1] = False
        else:
            valid[:, 0] = False
        color_distance = np.sum((lab - shifted_lab) ** 2, axis=2)
        affinity = np.exp(-color_distance / (2.0 * sigma * sigma)) * valid
        neighbor_labels.append(shifted_labels)
        affinities.append(affinity)
        valid_masks.append(valid)
    return neighbor_labels, affinities, valid_masks


def _component_regions(
    labels: NDArray[np.int16],
) -> tuple[list[SegmentedRegion], list[list[tuple[int, int]]]]:
    height, width = labels.shape
    visited = np.zeros(labels.shape, dtype=bool)
    regions: list[SegmentedRegion] = []
    pixels_by_region: list[list[tuple[int, int]]] = []
    for y in range(height):
        for x in range(width):
            label = _label_at(labels, x, y)
            if label < 0 or visited[y, x]:
                continue
            queue: deque[tuple[int, int]] = deque([(x, y)])
            visited[y, x] = True
            pixels: list[tuple[int, int]] = []
            left = right = x
            top = bottom = y
            touches_border = False
            while queue:
                current_x, current_y = queue.popleft()
                pixels.append((current_x, current_y))
                left = min(left, current_x)
                right = max(right, current_x)
                top = min(top, current_y)
                bottom = max(bottom, current_y)
                touches_border = touches_border or (
                    current_x == 0
                    or current_y == 0
                    or current_x + 1 == width
                    or current_y + 1 == height
                )
                for next_x, next_y in (
                    (current_x - 1, current_y),
                    (current_x + 1, current_y),
                    (current_x, current_y - 1),
                    (current_x, current_y + 1),
                ):
                    if (
                        0 <= next_x < width
                        and 0 <= next_y < height
                        and not visited[next_y, next_x]
                        and _label_at(labels, next_x, next_y) == label
                    ):
                        visited[next_y, next_x] = True
                        queue.append((next_x, next_y))
            region_id = len(regions)
            regions.append(
                SegmentedRegion(
                    region_id=region_id,
                    palette_index=label,
                    pixel_count=len(pixels),
                    bounding_box=(left, top, right + 1, bottom + 1),
                    touches_border=touches_border,
                )
            )
            pixels_by_region.append(pixels)
    return regions, pixels_by_region


def _remove_small_regions(labels: NDArray[np.int16], minimum_pixels: int) -> NDArray[np.int16]:
    if minimum_pixels <= 1:
        return labels
    output = labels.copy()
    regions, region_pixels = _component_regions(labels)
    height, width = labels.shape
    for region, pixels in zip(regions, region_pixels, strict=True):
        if region.pixel_count >= minimum_pixels:
            continue
        neighbor_counts: dict[int, int] = {}
        for x, y in pixels:
            for next_x, next_y in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                if 0 <= next_x < width and 0 <= next_y < height:
                    neighbor = _label_at(labels, next_x, next_y)
                    if neighbor >= 0 and neighbor != region.palette_index:
                        neighbor_counts[neighbor] = neighbor_counts.get(neighbor, 0) + 1
        if not neighbor_counts:
            continue
        replacement = min(neighbor_counts, key=lambda item: (-neighbor_counts[item], item))
        for x, y in pixels:
            output[y, x] = replacement
    return output


def segment_multicolor(
    image: NormalizedImage,
    palette: PaletteHypothesis,
    reliability: ReliabilityMap,
    config: SpatialSegmentationConfig | None = None,
) -> SpatialSegmentation:
    config = config or SpatialSegmentationConfig()
    _validate(image, palette, reliability, config)
    active = palette.labels >= 0
    lab = image.oklab.astype(np.float64, copy=False)
    centers = np.asarray([color.oklab for color in palette.colors], dtype=np.float64)
    data_energy = np.sum((lab[:, :, None, :] - centers[None, None, :, :]) ** 2, axis=3)
    confidence_weight = 0.25 + 0.75 * reliability.confidence.astype(np.float64, copy=False)
    data_energy *= confidence_weight[:, :, None]
    labels = palette.labels.copy()
    labels[active] = np.argmin(data_energy[active], axis=1).astype(np.int16)
    iterations_run = 0
    final_energy = data_energy
    for iteration in range(config.iterations):
        neighbors, affinities, valid_masks = _neighbor_terms(lab, labels, active, config.edge_sigma)
        energy = data_energy.copy()
        for cluster in range(palette.color_count):
            pairwise = np.zeros(labels.shape, dtype=np.float64)
            for neighbor, affinity, valid in zip(neighbors, affinities, valid_masks, strict=True):
                pairwise += affinity * valid * (neighbor != cluster)
            energy[..., cluster] += config.spatial_weight * pairwise
        updated = labels.copy()
        updated[active] = np.argmin(energy[active], axis=1).astype(np.int16)
        final_energy = energy
        iterations_run = iteration + 1
        if np.array_equal(updated, labels):
            labels = updated
            break
        labels = updated

    labels = _remove_small_regions(labels, config.minimum_region_pixels)
    if palette.color_count == 1:
        confidence = np.zeros(labels.shape, dtype=np.float32)
        confidence[active] = 1.0
    else:
        try:
            sorted_energy = np.partition(final_energy, kth=1, axis=2)
        except (TypeError, ValueError, FloatingPointError) as error:
            raise EngineFailure(
                EngineError(
                    ErrorCode.INTERNAL_INVARIANT_VIOLATION,
                    Stage.SEGMENTATION,
                    f"cannot compute segmentation confidence: {error}",
                )
            ) from error
        margin = sorted_energy[..., 1] - sorted_energy[..., 0]
        confidence = np.clip(margin / (margin + 0.02), 0.0, 1.0).astype(np.float32)
        confidence[~active] = 0.0
    labels.setflags(write=False)
    confidence.setflags(write=False)
    regions, _ = _component_regions(labels)
    return SpatialSegmentation(
        labels=labels,
        confidence=confidence,
        regions=tuple(regions),
        iterations_run=iterations_run,
    )
