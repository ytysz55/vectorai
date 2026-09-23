from __future__ import annotations

import json
from pathlib import Path

from PIL import Image
from python.tests._support import RGBA_PNG_WRITER_SOURCE, active_python_executable

from vectorai_bench.fixtures import generate_fixture_set
from vectorai_engine import OptimizationMode, RunStatus
from vectorai_engine.multicolor_pipeline import (
    MulticolorPipelineConfig,
    run_multicolor_pipeline,
)

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
    print('fake-resvg 1.0')
    raise SystemExit(0)
if '--width' in sys.argv:
    width = int(sys.argv[sys.argv.index('--width') + 1])
    height = int(sys.argv[sys.argv.index('--height') + 1])
    output = Path(sys.argv[-1])
elif any(arg.startswith('--export-width=') for arg in sys.argv):
    width = int(next(arg.split('=', 1)[1] for arg in sys.argv if arg.startswith('--export-width=')))
    height_arg = next(arg for arg in sys.argv if arg.startswith('--export-height='))
    output_arg = next(arg for arg in sys.argv if arg.startswith('--export-filename='))
    height = int(height_arg.split('=', 1)[1])
    output = Path(output_arg.split('=', 1)[1])
else:
    size_arg = next(arg for arg in sys.argv if arg.startswith('--window-size='))
    output_arg = next(arg for arg in sys.argv if arg.startswith('--screenshot='))
    width, height = map(int, size_arg.split('=', 1)[1].split(','))
    output = Path(output_arg.split('=', 1)[1])
write_rgba_png(output, width, height, (20, 30, 40, 255))
""".strip()
        + "\n",
        encoding="utf-8",
    )
    return (active_python_executable(), str(path))


def input_image(path: Path) -> None:
    image = Image.new("RGB", (30, 18))
    for x in range(30):
        color = (220, 20, 30) if x < 10 else (20, 180, 70) if x < 20 else (30, 60, 230)
        for y in range(18):
            image.putpixel((x, y), color)
    image.save(path)


def test_multicolor_pipeline_writes_atomic_scene_bundle(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    input_image(source)
    bundle = run_multicolor_pipeline(
        source,
        tmp_path / "bundle",
        MulticolorPipelineConfig(
            resvg_command_prefix=fake_resvg(tmp_path / "fake_resvg.py"),
        ),
    )
    assert bundle.final_status is RunStatus.SUCCESS
    assert bundle.svg_path.is_file()
    assert bundle.preview_path.is_file()
    scene = json.loads(bundle.scene_path.read_text(encoding="utf-8"))
    manifest = json.loads(bundle.manifest_path.read_text(encoding="utf-8"))
    assert scene["palette"]["selected_color_count"] == 3
    assert scene["segmentation"]["region_count"] == 3
    assert scene["graph"]["face_count"] == 3
    assert len(scene["shared_boundaries"]["seam_pairs"]) == 2
    assert manifest["final_status"] == "success"
    assert {artifact["name"] for artifact in manifest["artifacts"]} == {
        "output.svg",
        "preview.png",
        "scene.json",
    }


def test_representative_pipeline_preserves_topology_with_bounded_nodes(
    tmp_path: Path,
) -> None:
    fixture_root = tmp_path / "fixtures"
    manifest = generate_fixture_set(fixture_root)
    expected = {
        "synthetic-junction-001": (3, 0, 64),
        "synthetic-nested-001": (3, 0, 400),
        "synthetic-text-like-001": (4, 1, 64),
    }
    for case in manifest.cases:
        truth = expected.get(case.family_id)
        if truth is None or case.raster_asset is None:
            continue
        bundle = run_multicolor_pipeline(
            fixture_root / case.raster_asset.artifact_ref,
            tmp_path / f"bundle-{case.family_id}",
            MulticolorPipelineConfig(
                resvg_command_prefix=fake_resvg(tmp_path / f"resvg-{case.family_id}.py"),
            ),
        )
        scene = json.loads(bundle.scene_path.read_text(encoding="utf-8"))
        assert scene["graph"]["face_count"] == truth[0]
        assert scene["graph"]["hole_count"] == truth[1]
        assert scene["scene"]["editability"]["node_count"] < truth[2]


def test_optimizer_path_records_top_k_oracle_and_profile_hash(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    input_image(source)
    first = run_multicolor_pipeline(
        source,
        tmp_path / "optimized-a",
        MulticolorPipelineConfig(
            resvg_command_prefix=fake_resvg(tmp_path / "optimizer-resvg-a.py"),
            optimizer_profile_path=PROFILE_PATH,
            optimizer_mode=OptimizationMode.MINIMAL,
        ),
    )
    second = run_multicolor_pipeline(
        source,
        tmp_path / "optimized-b",
        MulticolorPipelineConfig(
            resvg_command_prefix=fake_resvg(tmp_path / "optimizer-resvg-b.py"),
            optimizer_profile_path=PROFILE_PATH,
            optimizer_mode=OptimizationMode.MINIMAL,
        ),
    )

    first_scene = json.loads(first.scene_path.read_text(encoding="utf-8"))
    second_scene = json.loads(second.scene_path.read_text(encoding="utf-8"))
    optimizer = first_scene["optimizer"]
    assert optimizer == second_scene["optimizer"]
    assert len(optimizer["profile_sha256"]) == 64
    assert optimizer["mode"] == "minimal"
    assert optimizer["selected_node_count"] <= optimizer["baseline_node_count"]
    assert optimizer["selected_candidate_id"] == optimizer["render_rank"]["winner_id"]
    assert all(len(score["observations"]) == 16 for score in optimizer["render_rank"]["scores"])


def test_optimizer_failure_uses_validated_degraded_fallback(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    input_image(source)
    bundle = run_multicolor_pipeline(
        source,
        tmp_path / "degraded",
        MulticolorPipelineConfig(
            resvg_command_prefix=fake_resvg(tmp_path / "fallback-resvg.py"),
            optimizer_profile_path=tmp_path / "missing-profiles.json",
        ),
    )

    scene = json.loads(bundle.scene_path.read_text(encoding="utf-8"))
    manifest = json.loads(bundle.manifest_path.read_text(encoding="utf-8"))
    assert bundle.final_status is RunStatus.DEGRADED
    assert scene["optimizer"] == {
        "fallback_reason": "ValueError",
        "fallback_used": True,
        "mode": "geometric",
        "status": "degraded",
    }
    assert manifest["final_status"] == "degraded"
    assert manifest["warnings"][-1] == "optimizer fallback: ValueError"


def test_pipeline_records_required_three_renderer_seam_matrix(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    input_image(source)
    renderer = fake_resvg(tmp_path / "fake_renderer.py")
    bundle = run_multicolor_pipeline(
        source,
        tmp_path / "bundle",
        MulticolorPipelineConfig(
            resvg_command_prefix=renderer,
            inkscape_command_prefix=renderer,
            chromium_command_prefix=renderer,
            require_auxiliary_renderers=True,
        ),
    )
    manifest = json.loads(bundle.manifest_path.read_text(encoding="utf-8"))
    assert [item["renderer"] for item in manifest["seams"]["observations"]] == [
        "chromium",
        "inkscape",
        "resvg",
    ]
    assert all(item["status"] == "success" for item in manifest["auxiliary_renderers"])
    assert {item["name"] for item in manifest["artifacts"]} == {
        "output.svg",
        "preview.png",
        "preview-chromium.png",
        "preview-inkscape.png",
        "scene.json",
    }


def test_multicolor_pipeline_rejects_existing_output(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    input_image(source)
    output = tmp_path / "exists"
    output.mkdir()
    try:
        run_multicolor_pipeline(
            source,
            output,
            MulticolorPipelineConfig(
                resvg_command_prefix=fake_resvg(tmp_path / "fake_resvg.py"),
            ),
        )
    except Exception as error:
        assert "already exists" in str(error)
    else:
        raise AssertionError("existing output must fail")
