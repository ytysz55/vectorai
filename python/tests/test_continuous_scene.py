from __future__ import annotations

import io
from pathlib import Path

import numpy as np
from PIL import Image

from vectorai_engine.continuous_scene import refine_palette_colors
from vectorai_engine.decode import decode_bytes
from vectorai_engine.normalize import normalize_source
from vectorai_engine.palette import PaletteColor, PaletteHypothesis, PaletteResult
from vectorai_engine.profiles import load_optimizer_profiles

ROOT = Path(__file__).resolve().parents[2]
PROFILE_PATH = ROOT / "benchmark" / "configs" / "optimizer-profiles-v1.json"


def red_source():  # type: ignore[no-untyped-def]
    image = Image.new("RGBA", (16, 16), (180, 20, 10, 255))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return normalize_source(decode_bytes(buffer.getvalue()))


def black_palette() -> PaletteResult:
    labels = np.zeros((16, 16), dtype=np.int16)
    labels.setflags(write=False)
    color = PaletteColor((0.0, 0.0, 0.0), (0.0, 0.0, 0.0), 1.0)
    selected = PaletteHypothesis(1, (color,), labels, 1.0, 1.0)
    return PaletteResult(selected, (selected,), 256)


def test_palette_color_refinement_connects_real_scene_to_parameter_backend() -> None:
    image = red_source()
    palette = black_palette()
    profile = load_optimizer_profiles(PROFILE_PATH).select("minimal")

    first = refine_palette_colors(image, palette, profile, baseline_node_count=4)
    second = refine_palette_colors(image, palette, profile, baseline_node_count=4)

    assert first == second
    assert first.selected_analytic_rmse < first.baseline_analytic_rmse
    selected = first.palette.selected.colors[0].rgb_srgb
    assert 0.0 < selected[0] <= profile.limits.max_color_delta
    assert selected[1] >= 0.0
    assert selected[2] >= 0.0
    assert first.palette.selected.labels is palette.selected.labels
    assert first.optimization.evaluations <= profile.limits.max_evaluations
    assert first.optimization.iterations <= profile.limits.max_iterations
