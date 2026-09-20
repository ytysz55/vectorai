from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

from vectorai_bench.baselines import VTracerAdapter, load_vtracer_lock
from vectorai_bench.external_tools import ToolStatus, file_sha256

ROOT = Path(__file__).resolve().parents[2]
LOCK_PATH = ROOT / "benchmark" / "configs" / "vtracer.lock.json"


def fake_vtracer(path: Path) -> tuple[str, ...]:
    path.write_text(
        """
import sys
import time
from pathlib import Path
if '--version' in sys.argv:
    print('visioncortex VTracer 0.6.4')
    raise SystemExit(0)
source = Path(sys.argv[sys.argv.index('--input') + 1])
output = Path(sys.argv[sys.argv.index('--output') + 1])
if 'slow' in source.name:
    time.sleep(1.0)
if 'invalid' in source.name:
    output.write_text('bad output', encoding='utf-8')
else:
    output.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg"><path d="M0 0L1 1"/></svg>',
        encoding='utf-8',
    )
""".strip()
        + "\n",
        encoding="utf-8",
    )
    return (sys.executable, str(path))


def write_png(path: Path) -> None:
    Image.new("RGBA", (16, 16), (20, 40, 60, 255)).save(path)


def test_vtracer_lock_pins_binaries_and_presets() -> None:
    windows = load_vtracer_lock(LOCK_PATH, "windows-x86_64")
    linux = load_vtracer_lock(LOCK_PATH, "linux-x86_64")
    assert windows.version == linux.version == "0.6.4"
    assert windows.version_output == "visioncortex VTracer 0.6.4"
    assert set(windows.presets) == {"faithful", "geometric", "minimal"}
    assert all(len(value) == 64 for value in (windows.archive_sha256, windows.executable_sha256))


def test_vtracer_success_records_identity_preset_and_hash(tmp_path: Path) -> None:
    lock = load_vtracer_lock(LOCK_PATH, "windows-x86_64")
    command = fake_vtracer(tmp_path / "fake_vtracer.py")
    raster = tmp_path / "input.png"
    output = tmp_path / "output.svg"
    write_png(raster)
    adapter = VTracerAdapter(
        presets=lock.presets,
        command_prefix=command,
        expected_version_output=lock.version_output,
        expected_executable_sha256=file_sha256(Path(sys.executable)),
    )
    result = adapter.vectorize(raster, output, preset_name="faithful")
    assert result.status is ToolStatus.SUCCESS
    assert result.identity is not None
    assert result.identity.version == lock.version_output
    assert result.preset == "faithful"
    assert result.arguments == lock.presets["faithful"].arguments
    assert result.output_sha256 is not None
    assert output.is_file()


def test_vtracer_unavailable_unknown_preset_timeout_and_invalid_output(tmp_path: Path) -> None:
    lock = load_vtracer_lock(LOCK_PATH, "windows-x86_64")
    unavailable = VTracerAdapter(presets=lock.presets, executable=tmp_path / "missing-vtracer")
    raster = tmp_path / "input.png"
    write_png(raster)
    assert (
        unavailable.vectorize(raster, tmp_path / "a.svg", preset_name="faithful").status
        is ToolStatus.UNAVAILABLE
    )
    assert (
        unavailable.vectorize(raster, tmp_path / "b.svg", preset_name="unknown").status
        is ToolStatus.FAILED
    )

    command = fake_vtracer(tmp_path / "fake_vtracer.py")
    adapter = VTracerAdapter(presets=lock.presets, command_prefix=command)
    slow = tmp_path / "slow.png"
    invalid = tmp_path / "invalid.png"
    write_png(slow)
    write_png(invalid)
    assert (
        adapter.vectorize(
            slow,
            tmp_path / "slow.svg",
            preset_name="faithful",
            timeout_seconds=0.05,
        ).status
        is ToolStatus.TIMEOUT
    )
    assert (
        adapter.vectorize(invalid, tmp_path / "invalid.svg", preset_name="faithful").status
        is ToolStatus.INVALID_OUTPUT
    )
