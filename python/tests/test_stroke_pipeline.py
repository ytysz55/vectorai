from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw
from python.tests._support import active_python_executable

from vectorai_engine.errors import RunStatus
from vectorai_engine.stroke_pipeline import StrokePipelineConfig, run_stroke_pipeline


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
Image.new('RGBA', (width, height), (0, 0, 0, 0)).save(Path(sys.argv[-1]))
""".strip()
        + "\n",
        encoding="utf-8",
    )
    return active_python_executable(), str(path)


def test_stroke_pipeline_writes_arbitrated_bundle(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    image = Image.new("RGBA", (96, 48), (0, 0, 0, 0))
    ImageDraw.Draw(image).line((12, 24, 84, 24), fill=(17, 24, 39, 255), width=7)
    image.save(source)

    bundle = run_stroke_pipeline(
        source,
        tmp_path / "bundle",
        StrokePipelineConfig(
            resvg_command_prefix=fake_resvg(tmp_path / "fake_resvg.py"),
            minimum_confident_margin=0.0,
        ),
    )

    assert bundle.final_status is RunStatus.SUCCESS
    assert bundle.svg_path.is_file()
    assert bundle.preview_path.is_file()
    assert bundle.cut_outline_path.is_file()
    scene = json.loads(bundle.scene_path.read_text(encoding="utf-8"))
    manifest = json.loads(bundle.manifest_path.read_text(encoding="utf-8"))
    assert scene["routing"]["selected"] == "stroke"
    assert scene["graph"]["component_count"] == 1
    assert scene["cut_outline_valid"]
    assert any(item["kind"] == "fill" for item in scene["arbitration"]["ranked"])
    assert any(item["kind"] == "stroke" for item in scene["arbitration"]["ranked"])
    assert manifest["best_stroke_candidate"].startswith("stroke-")
