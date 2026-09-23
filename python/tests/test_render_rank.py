from __future__ import annotations

from pathlib import Path

import numpy as np
from python.tests._support import RGBA_PNG_WRITER_SOURCE, active_python_executable

from vectorai_engine.profiles import load_optimizer_profiles
from vectorai_engine.render_rank import RenderRankCandidate, render_and_rank_candidates

ROOT = Path(__file__).resolve().parents[2]
PROFILE_PATH = ROOT / "benchmark" / "configs" / "optimizer-profiles-v1.json"


def fake_resvg(path: Path) -> tuple[str, ...]:
    path.write_text(
        RGBA_PNG_WRITER_SOURCE
        + "\n\n"
        + """
import sys
from pathlib import Path

if '--version' in sys.argv:
    print('0.47.0')
    raise SystemExit(0)
svg = Path(sys.argv[-2]).read_text(encoding='utf-8')
output = Path(sys.argv[-1])
width = int(sys.argv[sys.argv.index('--width') + 1])
height = int(sys.argv[sys.argv.index('--height') + 1])
color = (255, 0, 0, 255) if '#ff0000' in svg else (0, 0, 255, 255)
write_rgba_png(output, width, height, color)
""".strip()
        + "\n",
        encoding="utf-8",
    )
    return (active_python_executable(), str(path))


def svg(color: str) -> str:
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="8" height="8" '
        'viewBox="0 0 8 8">'
        f'<rect width="8" height="8" fill="{color}"/>'
        "</svg>"
    )


def test_top_k_resvg_ranks_all_scales_and_backgrounds_deterministically(
    tmp_path: Path,
) -> None:
    profile = load_optimizer_profiles(PROFILE_PATH).select("faithful")
    reference = np.zeros((8, 8, 4), dtype=np.uint8)
    reference[..., 0] = 255
    reference[..., 3] = 255
    candidates = (
        RenderRankCandidate("blue-low-objective", svg("#0000ff"), 4, 0.01, True),
        RenderRankCandidate("red-oracle-winner", svg("#ff0000"), 8, 0.02, True),
        RenderRankCandidate("red-compact", svg("#ff0000"), 3, 0.03, True),
        RenderRankCandidate("invalid", svg("#ff0000"), 1, 0.0, False),
    )

    first = render_and_rank_candidates(
        candidates,
        reference,
        profile.render_and_rank,
        top_k=profile.limits.top_k,
        resvg_command_prefix=fake_resvg(tmp_path / "fake_resvg.py"),
    )
    second = render_and_rank_candidates(
        candidates,
        reference,
        profile.render_and_rank,
        top_k=profile.limits.top_k,
        resvg_command_prefix=fake_resvg(tmp_path / "fake_resvg_repeat.py"),
    )

    assert first == second
    assert first.winner_id == "red-compact"
    assert first.unique_svg_count == 2
    assert first.candidate_order == (
        "blue-low-objective",
        "red-oracle-winner",
        "red-compact",
    )
    assert tuple(score.candidate_id for score in first.scores) == (
        "red-compact",
        "red-oracle-winner",
        "blue-low-objective",
    )
    assert first.scores[0].aggregate_rmse == 0.0
    assert len(first.scores[0].observations) == 16
    assert {item.scale for item in first.scores[0].observations} == {0.5, 1.0, 2.0, 4.0}
    assert {item.background for item in first.scores[0].observations} == {
        "transparent",
        "black",
        "white",
        "checkerboard",
    }
