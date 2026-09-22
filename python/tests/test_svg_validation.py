from __future__ import annotations

from pathlib import Path

from python.tests._support import active_python_executable

from vectorai_bench.external_tools import ToolStatus
from vectorai_bench.renderers import ResvgAdapter
from vectorai_bench.svg_validation import (
    ChromiumAdapter,
    InkscapeAdapter,
    ValidationStatus,
    validate_svg_renderers,
)


def write_fake_renderer(path: Path, *, color: tuple[int, int, int, int]) -> tuple[str, ...]:
    path.write_text(
        f"""
import sys
from pathlib import Path
from PIL import Image

if '--version' in sys.argv:
    print('fake-1.0')
    raise SystemExit(0)
width = 1
height = 1
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
Image.new('RGBA', (width, height), {color!r}).save(output)
""".strip()
        + "\n",
        encoding="utf-8",
    )
    return (active_python_executable(), str(path))


def write_svg(path: Path) -> None:
    path.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="8" height="6"/>',
        encoding="utf-8",
    )


def test_three_renderers_pass_when_outputs_agree(tmp_path: Path) -> None:
    command = write_fake_renderer(tmp_path / "renderer.py", color=(10, 20, 30, 255))
    svg = tmp_path / "input.svg"
    write_svg(svg)
    result = validate_svg_renderers(
        svg,
        tmp_path / "renders",
        width=8,
        height=6,
        resvg=ResvgAdapter(command_prefix=command),
        inkscape=InkscapeAdapter(command_prefix=command),
        chromium=ChromiumAdapter(command_prefix=command),
        require_auxiliary=True,
    )
    assert result.status is ValidationStatus.PASSED
    assert [check.name for check in result.checks] == ["resvg", "inkscape", "chromium"]
    assert all(check.status is ToolStatus.SUCCESS for check in result.checks)
    assert result.checks[1].premultiplied_rgba_rmse == 0.0
    assert result.checks[2].premultiplied_rgba_rmse == 0.0


def test_renderer_disagreement_requires_review(tmp_path: Path) -> None:
    reference = write_fake_renderer(tmp_path / "reference.py", color=(0, 0, 0, 255))
    different = write_fake_renderer(tmp_path / "different.py", color=(255, 255, 255, 255))
    svg = tmp_path / "input.svg"
    write_svg(svg)
    result = validate_svg_renderers(
        svg,
        tmp_path / "renders",
        width=8,
        height=6,
        resvg=ResvgAdapter(command_prefix=reference),
        inkscape=InkscapeAdapter(command_prefix=different),
        disagreement_rmse=0.01,
    )
    assert result.status is ValidationStatus.NEEDS_REVIEW
    assert result.checks[1].premultiplied_rgba_rmse == 0.8660254037844386


def test_required_auxiliary_renderers_must_be_supplied(tmp_path: Path) -> None:
    command = write_fake_renderer(tmp_path / "renderer.py", color=(10, 20, 30, 255))
    svg = tmp_path / "input.svg"
    write_svg(svg)
    result = validate_svg_renderers(
        svg,
        tmp_path / "renders",
        width=8,
        height=6,
        resvg=ResvgAdapter(command_prefix=command),
        require_auxiliary=True,
    )
    assert result.status is ValidationStatus.FAILED
