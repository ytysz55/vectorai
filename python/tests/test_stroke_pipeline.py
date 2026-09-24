from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]
from PIL import Image, ImageDraw
from python.tests._support import RGBA_PNG_WRITER_SOURCE, active_python_executable

from vectorai_engine.cut_ready import CutReadyPolicy
from vectorai_engine.errors import EngineFailure, RunStatus
from vectorai_engine.stroke_pipeline import StrokePipelineConfig, run_stroke_pipeline


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
width = int(sys.argv[sys.argv.index('--width') + 1])
height = int(sys.argv[sys.argv.index('--height') + 1])
write_rgba_png(Path(sys.argv[-1]), width, height, (0, 0, 0, 0))
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
    validation = json.loads(bundle.validation_path.read_text(encoding="utf-8"))
    assert validation["status"] == "passed"
    assert validation["summary"]["hard_failures"] == 0
    scene = json.loads(bundle.scene_path.read_text(encoding="utf-8"))
    manifest = json.loads(bundle.manifest_path.read_text(encoding="utf-8"))
    schema_path = Path(__file__).resolve().parents[2] / "schemas/run-manifest.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    cast(Any, Draft202012Validator(schema)).validate(manifest)
    events = (bundle.output_directory / "events.jsonl").read_text(encoding="utf-8")
    assert "STAGE_COMPLETED" in events
    assert str(source) not in events
    assert scene["routing"]["selected"] == "stroke"
    assert scene["graph"]["component_count"] == 1
    assert scene["cut_outline_valid"]
    assert any(item["kind"] == "fill" for item in scene["arbitration"]["ranked"])
    assert any(item["kind"] == "stroke" for item in scene["arbitration"]["ranked"])
    assert manifest["best_stroke_candidate"].startswith("stroke-")
    assert "validation-report.json" in {item["name"] for item in manifest["artifacts"]}
    assert "events.jsonl" in {item["name"] for item in manifest["artifacts"]}


def test_stroke_pipeline_opt_in_cut_ready_sizes_svg_and_rejects_bad_ratio(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    image = Image.new("RGBA", (96, 48), (0, 0, 0, 0))
    ImageDraw.Draw(image).line((12, 24, 84, 24), fill=(17, 24, 39, 255), width=7)
    image.save(source)
    renderer = fake_resvg(tmp_path / "renderer.py")
    bundle = run_stroke_pipeline(
        source,
        tmp_path / "cut-ready",
        StrokePipelineConfig(
            resvg_command_prefix=renderer,
            minimum_confident_margin=0.0,
            cut_ready_policy=CutReadyPolicy(96.0, 48.0),
        ),
    )
    assert 'width="96mm" height="48mm"' in bundle.cut_outline_path.read_text(encoding="utf-8")
    assert json.loads(bundle.scene_path.read_text(encoding="utf-8"))["cut_ready"]
    report = json.loads(bundle.validation_path.read_text(encoding="utf-8"))
    assert any(gate["id"] == "CUT_READY.PHYSICAL_POLICY" for gate in report["gates"])

    invalid = tmp_path / "invalid-cut"
    try:
        run_stroke_pipeline(
            source,
            invalid,
            StrokePipelineConfig(
                resvg_command_prefix=renderer,
                minimum_confident_margin=0.0,
                cut_ready_policy=CutReadyPolicy(96.0, 49.0),
            ),
        )
    except EngineFailure as error:
        assert "CUT_READY.UNIFORM_SCALE" in error.error.context["finding_codes"]
    else:
        raise AssertionError("invalid physical scale must fail hard")
    assert not invalid.exists()
