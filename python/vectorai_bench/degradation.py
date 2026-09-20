"""Seed-controlled raster degradation pipeline with explicit parameters."""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter
from PIL import __version__ as pillow_version

from .manifest import load_manifest, write_manifest
from .models import BenchmarkCase, DatasetManifest, JsonValue, SourceAsset, Variant, VariantTier

PIPELINE_VERSION = "1.0.0"
MAX_INPUT_PIXELS = 16_777_216


@dataclass(frozen=True, slots=True)
class DegradationRecipe:
    recipe_id: str
    tier: VariantTier
    width: int
    height: int
    seed: int
    jpeg_quality: int | None = None
    blur_radius: float = 0.0
    alpha_bits: int = 8
    background: tuple[int, int, int] | None = None
    noise_sigma: float = 0.0

    def __post_init__(self) -> None:
        if self.width < 1 or self.height < 1 or self.seed < 0:
            raise ValueError("recipe dimensions and seed are out of range")
        if self.jpeg_quality is not None and not 1 <= self.jpeg_quality <= 95:
            raise ValueError("jpeg_quality must be between 1 and 95")
        if self.blur_radius < 0.0 or not 1 <= self.alpha_bits <= 8 or self.noise_sigma < 0.0:
            raise ValueError("recipe blur, alpha, or noise value is out of range")
        if self.background is not None and any(
            not 0 <= channel <= 255 for channel in self.background
        ):
            raise ValueError("background channels must be between 0 and 255")


def default_recipes() -> tuple[DegradationRecipe, ...]:
    return (
        DegradationRecipe("t0-pristine", VariantTier.T0, 256, 256, 2100),
        DegradationRecipe(
            "t1-resize",
            VariantTier.T1,
            128,
            128,
            2101,
            blur_radius=0.25,
        ),
        DegradationRecipe(
            "t2-jpeg",
            VariantTier.T2,
            96,
            96,
            2102,
            jpeg_quality=72,
            blur_radius=0.6,
            noise_sigma=1.2,
        ),
        DegradationRecipe(
            "t3-hostile",
            VariantTier.T3,
            64,
            64,
            2103,
            jpeg_quality=34,
            blur_radius=1.1,
            alpha_bits=4,
            background=(247, 244, 235),
            noise_sigma=2.5,
        ),
    )


def derive_case_seed(base_seed: int, family_id: str) -> int:
    digest = hashlib.sha256(f"{base_seed}:{family_id}".encode()).digest()
    return int.from_bytes(digest[:8], "big")


def _quantize_alpha(alpha: Image.Image, bits: int) -> Image.Image:
    if bits == 8:
        return alpha
    levels = (1 << bits) - 1
    values = np.asarray(alpha, dtype=np.float32)
    quantized = np.rint(values * levels / 255.0) * (255.0 / levels)
    return Image.fromarray(np.clip(quantized, 0, 255).astype(np.uint8), mode="L")


def _add_noise(image: Image.Image, sigma: float, seed: int) -> Image.Image:
    if sigma == 0.0:
        return image
    pixels = np.asarray(image, dtype=np.float32)
    noise = np.random.default_rng(seed).normal(0.0, sigma, size=pixels.shape)
    noisy = np.clip(np.rint(pixels + noise), 0, 255).astype(np.uint8)
    return Image.fromarray(noisy, mode=image.mode)


def _jpeg_roundtrip(image: Image.Image, quality: int) -> Image.Image:
    buffer = io.BytesIO()
    image.save(
        buffer,
        format="JPEG",
        quality=quality,
        subsampling=2,
        optimize=False,
        progressive=False,
    )
    buffer.seek(0)
    with Image.open(buffer) as decoded:
        return decoded.convert("RGB")


def apply_degradation(
    source: Image.Image, recipe: DegradationRecipe, *, case_seed: int
) -> Image.Image:
    rgba = source.convert("RGBA")
    if rgba.width * rgba.height > MAX_INPUT_PIXELS:
        raise ValueError(f"input exceeds {MAX_INPUT_PIXELS} pixels")

    rgba = rgba.resize((recipe.width, recipe.height), Image.Resampling.LANCZOS)
    if recipe.blur_radius > 0.0:
        rgba = rgba.filter(ImageFilter.GaussianBlur(recipe.blur_radius))

    red, green, blue, alpha = rgba.split()
    alpha = _quantize_alpha(alpha, recipe.alpha_bits)
    color = Image.merge("RGB", (red, green, blue))
    color = _add_noise(color, recipe.noise_sigma, case_seed)

    if recipe.background is not None:
        foreground = Image.merge("RGBA", (*color.split(), alpha))
        background = Image.new("RGBA", foreground.size, (*recipe.background, 255))
        color = Image.alpha_composite(background, foreground).convert("RGB")
        alpha = Image.new("L", color.size, 255)

    if recipe.jpeg_quality is not None:
        color = _jpeg_roundtrip(color, recipe.jpeg_quality)

    return Image.merge("RGBA", (*color.split(), alpha))


def recipe_parameters(recipe: DegradationRecipe) -> dict[str, JsonValue]:
    return {
        "pipeline_version": PIPELINE_VERSION,
        "resize_kernel": "lanczos",
        "operation_colorspace": "srgb",
        "jpeg_quality": recipe.jpeg_quality,
        "jpeg_subsampling": 2 if recipe.jpeg_quality is not None else None,
        "blur_radius": recipe.blur_radius,
        "alpha_bits": recipe.alpha_bits,
        "background_rgb": list(recipe.background) if recipe.background is not None else None,
        "noise_sigma": recipe.noise_sigma,
        "pillow_version": pillow_version,
        "numpy_version": np.__version__,
    }


def _safe_artifact_path(dataset_dir: Path, artifact_ref: str) -> Path:
    root = dataset_dir.resolve()
    candidate = (root / artifact_ref).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as error:
        raise ValueError(f"artifact escapes dataset root: {artifact_ref}") from error
    return candidate


def generate_degraded_variants(
    dataset_dir: Path,
    recipes: tuple[DegradationRecipe, ...] | None = None,
) -> DatasetManifest:
    active_recipes = default_recipes() if recipes is None else recipes
    if len({recipe.recipe_id for recipe in active_recipes}) != len(active_recipes):
        raise ValueError("recipe_id values must be unique")

    manifest = load_manifest(dataset_dir / "manifest.json")
    source_cases = {case.family_id: case for case in manifest.cases}
    if len(source_cases) != len(manifest.families):
        raise ValueError("fixture manifest must contain exactly one source case per family")

    cases: list[BenchmarkCase] = []
    for family in manifest.families:
        source_case = source_cases[family.family_id]
        if source_case.raster_asset is None:
            raise ValueError(f"source case has no raster asset: {source_case.case_id}")
        source_path = _safe_artifact_path(dataset_dir, source_case.raster_asset.artifact_ref)
        with Image.open(source_path) as source_image:
            source = source_image.convert("RGBA")

        for recipe in active_recipes:
            case_seed = derive_case_seed(recipe.seed, family.family_id)
            degraded = apply_degradation(source, recipe, case_seed=case_seed)
            artifact_ref = f"variants/{family.family_id}/{recipe.recipe_id}.png"
            output_path = _safe_artifact_path(dataset_dir, artifact_ref)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            degraded.save(output_path, format="PNG", optimize=False, compress_level=9)
            payload = output_path.read_bytes()
            raster_asset = SourceAsset(
                sha256=hashlib.sha256(payload).hexdigest(),
                media_type="image/png",
                artifact_ref=artifact_ref,
                provenance=(
                    f"{source_case.raster_asset.sha256} degraded by VectorAI pipeline "
                    f"{PIPELINE_VERSION} recipe {recipe.recipe_id}"
                ),
                license_id=source_case.raster_asset.license_id,
            )
            cases.append(
                BenchmarkCase(
                    case_id=f"{family.family_id}-{recipe.recipe_id}",
                    family_id=family.family_id,
                    variant=Variant(
                        tier=recipe.tier,
                        seed=case_seed,
                        width=recipe.width,
                        height=recipe.height,
                        parameters=recipe_parameters(recipe),
                    ),
                    raster_asset=raster_asset,
                )
            )

    degraded_manifest = DatasetManifest(
        schema_version=manifest.schema_version,
        dataset_id=f"{manifest.dataset_id}-degraded",
        families=manifest.families,
        cases=tuple(sorted(cases, key=lambda case: case.case_id)),
    )
    write_manifest(dataset_dir / "manifest.json", degraded_manifest)
    return degraded_manifest
