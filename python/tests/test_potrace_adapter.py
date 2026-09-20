from __future__ import annotations

import sys
from pathlib import Path

from vectorai_bench.baselines import PotraceAdapter, load_potrace_lock
from vectorai_bench.external_tools import ToolStatus, file_sha256

ROOT = Path(__file__).resolve().parents[2]
LOCK_PATH = ROOT / "benchmark" / "configs" / "potrace.lock.json"


def fake_potrace(path: Path) -> tuple[str, ...]:
    path.write_text(
        """
import sys
import time
from pathlib import Path
if '--version' in sys.argv:
    print('potrace 1.16. Copyright (C) 2001-2019 Peter Selinger.')
    print('Library version: potracelib 1.16')
    raise SystemExit(0)
source = Path(sys.argv[-1])
output = Path(sys.argv[sys.argv.index('--output') + 1])
if 'slow' in source.name:
    time.sleep(1.0)
output.write_text(
    '<svg xmlns="http://www.w3.org/2000/svg"><path d="M0 0L1 1Z"/></svg>',
    encoding='utf-8',
)
""".strip()
        + "\n",
        encoding="utf-8",
    )
    return (sys.executable, str(path))


def write_pbm(path: Path) -> None:
    path.write_bytes(b"P4\n2 2\n\x90")


def test_potrace_lock_records_gpl_isolation_and_pins_windows_binary() -> None:
    windows = load_potrace_lock(LOCK_PATH, "windows-x86_64")
    linux = load_potrace_lock(LOCK_PATH, "linux-x86_64")
    assert windows.version == linux.version == "1.16"
    assert windows.executable_sha256 is not None
    assert len(windows.executable_sha256) == 64
    assert linux.executable_sha256 is None
    assert set(windows.presets) == {"faithful", "geometric", "minimal"}


def test_potrace_runs_only_through_isolated_process(tmp_path: Path) -> None:
    lock = load_potrace_lock(LOCK_PATH, "windows-x86_64")
    command = fake_potrace(tmp_path / "fake_potrace.py")
    source = tmp_path / "source.pbm"
    output = tmp_path / "output.svg"
    write_pbm(source)
    adapter = PotraceAdapter(
        presets=lock.presets,
        command_prefix=command,
        expected_version_output=lock.version_output,
        expected_executable_sha256=file_sha256(Path(sys.executable)),
    )
    result = adapter.vectorize(source, output, preset_name="faithful")
    assert result.status is ToolStatus.SUCCESS
    assert result.baseline == "potrace"
    assert result.identity is not None
    assert result.output_sha256 is not None
    assert output.is_file()


def test_potrace_rejects_non_binary_inputs_before_execution(tmp_path: Path) -> None:
    lock = load_potrace_lock(LOCK_PATH, "windows-x86_64")
    command = fake_potrace(tmp_path / "fake_potrace.py")
    source = tmp_path / "source.png"
    source.write_bytes(b"not a pbm")
    result = PotraceAdapter(presets=lock.presets, command_prefix=command).vectorize(
        source, tmp_path / "output.svg", preset_name="faithful"
    )
    assert result.status is ToolStatus.FAILED
    assert "only PBM" in result.message


def test_potrace_timeout_is_typed(tmp_path: Path) -> None:
    lock = load_potrace_lock(LOCK_PATH, "windows-x86_64")
    command = fake_potrace(tmp_path / "fake_potrace.py")
    source = tmp_path / "slow.pbm"
    write_pbm(source)
    result = PotraceAdapter(presets=lock.presets, command_prefix=command).vectorize(
        source,
        tmp_path / "output.svg",
        preset_name="faithful",
        timeout_seconds=0.05,
    )
    assert result.status is ToolStatus.TIMEOUT
