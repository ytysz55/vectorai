from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

from vectorai_bench.external_tools import ToolStatus, file_sha256
from vectorai_bench.renderers import ResvgAdapter, load_resvg_release

ROOT = Path(__file__).resolve().parents[2]


def write_fake_resvg(path: Path) -> tuple[str, ...]:
    path.write_text(
        """
import sys
import time
from pathlib import Path
from PIL import Image

if '--version' in sys.argv:
    print('0.47.0')
    raise SystemExit(0)
svg = Path(sys.argv[-2])
output = Path(sys.argv[-1])
if 'slow' in svg.name:
    time.sleep(1.0)
if 'invalid' in svg.name:
    output.write_text('not a png', encoding='utf-8')
    raise SystemExit(0)
width = int(sys.argv[sys.argv.index('--width') + 1])
height = int(sys.argv[sys.argv.index('--height') + 1])
Image.new('RGBA', (width, height), (10, 20, 30, 255)).save(output)
""".strip()
        + "\n",
        encoding="utf-8",
    )
    return (sys.executable, str(path))


def write_svg(path: Path) -> None:
    path.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"/>',
        encoding="utf-8",
    )


def test_release_lock_pins_windows_and_linux_archives() -> None:
    lock = ROOT / "benchmark" / "configs" / "resvg.lock.json"
    linux = load_resvg_release(lock, "linux-x86_64")
    windows = load_resvg_release(lock, "windows-x86_64")
    assert linux.version == windows.version == "0.47.0"
    assert len(linux.archive_sha256) == len(windows.archive_sha256) == 64
    assert len(linux.executable_sha256) == len(windows.executable_sha256) == 64
    assert linux.archive_sha256 != windows.archive_sha256
    assert linux.executable_sha256 != windows.executable_sha256


def test_unavailable_renderer_is_reported_without_exception(tmp_path: Path) -> None:
    adapter = ResvgAdapter(executable=tmp_path / "missing-resvg")
    result = adapter.render(tmp_path / "input.svg", tmp_path / "output.png", width=10, height=10)
    assert result.status is ToolStatus.UNAVAILABLE


def test_fake_renderer_is_probed_and_output_is_validated(tmp_path: Path) -> None:
    command = write_fake_resvg(tmp_path / "fake_resvg.py")
    svg = tmp_path / "input.svg"
    write_svg(svg)
    output = tmp_path / "output.png"
    adapter = ResvgAdapter(
        command_prefix=command,
        expected_version_output="0.47.0",
        expected_executable_sha256=file_sha256(Path(sys.executable)),
    )
    result = adapter.render(svg, output, width=40, height=30)
    assert result.status is ToolStatus.SUCCESS
    assert result.identity is not None
    assert result.identity.version == "0.47.0"
    assert result.output_sha256 is not None
    with Image.open(output) as image:
        assert image.size == (40, 30)


def test_checksum_mismatch_blocks_execution(tmp_path: Path) -> None:
    command = write_fake_resvg(tmp_path / "fake_resvg.py")
    adapter = ResvgAdapter(
        command_prefix=command,
        expected_version_output="0.47.0",
        expected_executable_sha256="0" * 64,
    )
    assert adapter.probe().status is ToolStatus.VERSION_MISMATCH


def test_timeout_and_invalid_output_are_typed(tmp_path: Path) -> None:
    command = write_fake_resvg(tmp_path / "fake_resvg.py")
    adapter = ResvgAdapter(command_prefix=command)

    slow_svg = tmp_path / "slow.svg"
    write_svg(slow_svg)
    timeout = adapter.render(
        slow_svg, tmp_path / "slow.png", width=10, height=10, timeout_seconds=0.05
    )
    assert timeout.status is ToolStatus.TIMEOUT

    invalid_svg = tmp_path / "invalid.svg"
    write_svg(invalid_svg)
    invalid = adapter.render(invalid_svg, tmp_path / "invalid.png", width=10, height=10)
    assert invalid.status is ToolStatus.INVALID_OUTPUT


def test_known_potrace_doctype_requires_explicit_opt_in(tmp_path: Path) -> None:
    command = write_fake_resvg(tmp_path / "fake_resvg.py")
    svg = tmp_path / "potrace.svg"
    svg.write_text(
        '<?xml version="1.0"?>\n'
        '<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 20010904//EN"\n'
        ' "http://www.w3.org/TR/2001/REC-SVG-20010904/DTD/svg10.dtd">\n'
        '<svg xmlns="http://www.w3.org/2000/svg"/>',
        encoding="utf-8",
    )
    adapter = ResvgAdapter(command_prefix=command)
    rejected = adapter.render(svg, tmp_path / "rejected.png", width=10, height=10)
    accepted = adapter.render(
        svg,
        tmp_path / "accepted.png",
        width=10,
        height=10,
        allow_known_svg_10_doctype=True,
    )
    assert rejected.status is ToolStatus.FAILED
    assert accepted.status is ToolStatus.SUCCESS


def test_external_resource_svg_is_rejected(tmp_path: Path) -> None:
    command = write_fake_resvg(tmp_path / "fake_resvg.py")
    svg = tmp_path / "external.svg"
    svg.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg"><image href="https://example.com/x"/></svg>',
        encoding="utf-8",
    )
    result = ResvgAdapter(command_prefix=command).render(
        svg, tmp_path / "output.png", width=10, height=10
    )
    assert result.status is ToolStatus.FAILED
    assert "external resources" in result.message
