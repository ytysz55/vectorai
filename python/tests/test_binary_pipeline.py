from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]
from PIL import Image, ImageDraw
from python.tests._support import RGBA_PNG_WRITER_SOURCE, active_python_executable

from vectorai_cli.__main__ import main
from vectorai_engine import BinaryPipelineConfig, RunStatus, run_binary_pipeline

ROOT = Path(__file__).resolve().parents[2]


def write_fake_native(path: Path) -> tuple[str, ...]:
    path.write_text(
        """
import json
import sys
from pathlib import Path


def value(name):
    return Path(sys.argv[sys.argv.index(name) + 1])

payload = value('--input').read_bytes()
header, pixels = payload.split(bytes((50, 53, 53, 10)), 1)
tokens = header.split()
width = int(tokens[1])
height = int(tokens[2])
svg = (
    f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
    f'viewBox="0 0 {width} {height}">\\n'
    f'  <path fill="#000000" fill-rule="evenodd" d="M2 2 L{width-2} 2 '
    f'L{width-2} {height-2} L2 {height-2} L2 2 Z"/>\\n</svg>\\n'
)
value('--output').write_text(svg, encoding='utf-8')
report = {
    'status': 'success',
    'width': width,
    'height': height,
    'threshold': 0.5,
    'components': 1,
    'holes': 0,
    'euler': 1,
    'canonical_edges': 20,
    'boundary_samples': 20,
    'candidate_count': 3,
    'selected_shapes': 1,
    'segments': 4,
    'nodes': 4,
}
value('--report').write_text(json.dumps(report, sort_keys=True) + '\\n', encoding='utf-8')
""".strip()
        + "\n",
        encoding="utf-8",
    )
    return (active_python_executable(), str(path))


def write_fake_renderer(path: Path) -> tuple[str, ...]:
    path.write_text(
        RGBA_PNG_WRITER_SOURCE
        + "\n\n"
        + """
import sys
from pathlib import Path

if '--version' in sys.argv:
    print('fake-1.0')
    raise SystemExit(0)
width = height = 1
output = None
if '--width' in sys.argv:
    width = int(sys.argv[sys.argv.index('--width') + 1])
    height = int(sys.argv[sys.argv.index('--height') + 1])
    output = Path(sys.argv[-1])
for argument in sys.argv:
    if argument.startswith('--export-width='):
        width = int(argument.split('=', 1)[1])
    elif argument.startswith('--export-height='):
        height = int(argument.split('=', 1)[1])
    elif argument.startswith('--export-filename='):
        output = Path(argument.split('=', 1)[1])
    elif argument.startswith('--window-size='):
        width, height = (int(value) for value in argument.split('=', 1)[1].split(','))
    elif argument.startswith('--screenshot='):
        output = Path(argument.split('=', 1)[1])
assert output is not None
write_rgba_png(output, width, height, (0, 0, 0, 0))
""".strip()
        + "\n",
        encoding="utf-8",
    )
    return (active_python_executable(), str(path))


def load_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return cast(dict[str, Any], payload)


def pipeline_config(tmp_path: Path) -> BinaryPipelineConfig:
    native = write_fake_native(tmp_path / "fake_native.py")
    renderer = write_fake_renderer(tmp_path / "fake_renderer.py")
    return BinaryPipelineConfig(
        native_executable=Path(active_python_executable()),
        native_command_prefix=native,
        resvg_command_prefix=renderer,
        inkscape_command_prefix=renderer,
        chromium_command_prefix=renderer,
    )


def source_image(path: Path) -> None:
    image = Image.new("RGB", (16, 12), "white")
    ImageDraw.Draw(image).rectangle((2, 2, 13, 9), fill="black")
    image.save(path)


def test_pipeline_writes_schema_valid_artifact_bundle(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    source_image(source)
    bundle = run_binary_pipeline(source, tmp_path / "bundle", pipeline_config(tmp_path))
    assert bundle.final_status is RunStatus.SUCCESS
    assert bundle.svg_path.is_file()
    assert (bundle.output_directory / "preview.png").is_file()
    assert (bundle.output_directory / "metrics.json").is_file()
    assert bundle.native_report_path.is_file()

    manifest = load_object(bundle.manifest_path)
    validation = load_object(bundle.validation_path)
    manifest_schema = load_object(ROOT / "schemas" / "run-manifest.schema.json")
    validation_schema = load_object(ROOT / "schemas" / "validation-report.schema.json")
    cast(Any, Draft202012Validator(manifest_schema).validate)(manifest)
    cast(Any, Draft202012Validator(validation_schema).validate)(validation)
    assert manifest["summary"] == {
        "candidates": 3,
        "edges": 20,
        "optimizer_iterations": 0,
        "regions": 1,
    }
    assert validation["status"] == "passed"
    assert len(validation["gates"]) == 4


def test_pipeline_semantic_outputs_repeat(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    source_image(source)
    config = pipeline_config(tmp_path)
    first = run_binary_pipeline(source, tmp_path / "first", config)
    second = run_binary_pipeline(source, tmp_path / "second", config)
    assert first.svg_path.read_bytes() == second.svg_path.read_bytes()
    assert first.native_report_path.read_bytes() == second.native_report_path.read_bytes()
    first_manifest = load_object(first.manifest_path)
    second_manifest = load_object(second.manifest_path)
    for manifest in (first_manifest, second_manifest):
        manifest["resources"] = {}
        for stage in manifest["stages"]:
            stage["duration_ms"] = 0.0
    assert first_manifest == second_manifest


def test_cli_vectorize_reports_bundle(tmp_path: Path, capsys: object) -> None:
    source = tmp_path / "source.png"
    source_image(source)
    native = write_fake_native(tmp_path / "fake_native.py")
    output = tmp_path / "bundle"
    exit_code = main(
        [
            "vectorize",
            str(source),
            "--output-dir",
            str(output),
            "--native-executable",
            str(tmp_path / "missing-native"),
        ]
    )
    assert exit_code == 2
    captured = cast(Any, capsys).readouterr()
    error = json.loads(cast(str, captured.err))
    assert error["code"] == "UNSUPPORTED_INPUT"
    assert native[0] == active_python_executable()
