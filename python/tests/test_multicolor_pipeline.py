from __future__ import annotations

import json
import sys
from pathlib import Path

from PIL import Image

from vectorai_engine import RunStatus
from vectorai_engine.multicolor_pipeline import (
    MulticolorPipelineConfig,
    run_multicolor_pipeline,
)


def fake_resvg(path: Path) -> tuple[str, ...]:
    path.write_text(
        """
import sys
from pathlib import Path
from PIL import Image

if '--version' in sys.argv:
    print('fake-resvg 1.0')
    raise SystemExit(0)
width = int(sys.argv[sys.argv.index('--width') + 1])
height = int(sys.argv[sys.argv.index('--height') + 1])
Image.new('RGBA', (width, height), (20, 30, 40, 255)).save(Path(sys.argv[-1]))
""".strip()
        + "\n",
        encoding="utf-8",
    )
    return (sys.executable, str(path))


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
