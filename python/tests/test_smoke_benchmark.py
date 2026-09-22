from __future__ import annotations

from pathlib import Path

from python.tests._support import active_python_executable

from vectorai_bench.baselines import (
    PotraceAdapter,
    VTracerAdapter,
    load_potrace_lock,
    load_vtracer_lock,
)
from vectorai_bench.external_tools import file_sha256
from vectorai_bench.renderers import ResvgAdapter
from vectorai_bench.smoke import run_smoke_benchmark, verify_repeatability

ROOT = Path(__file__).resolve().parents[2]
CONFIGS = ROOT / "benchmark" / "configs"


def write_fake_vectorizer(path: Path, version: str, kind: str) -> tuple[str, ...]:
    path.write_text(
        f"""
import sys
from pathlib import Path
if '--version' in sys.argv:
    print({version!r})
    raise SystemExit(0)
if {kind!r} == 'vtracer':
    output = Path(sys.argv[sys.argv.index('--output') + 1])
else:
    output = Path(sys.argv[sys.argv.index('--output') + 1])
output.write_text(
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128">'
    '<path fill="#7c3aed" fill-rule="evenodd" '
    'd="M64 8A56 56 0 1 1 63.999 8Z M64 36A28 28 0 1 0 64.001 36Z"/>'
    '</svg>',
    encoding='utf-8',
)
""".strip()
        + "\n",
        encoding="utf-8",
    )
    return (active_python_executable(), str(path))


def write_fake_resvg(path: Path) -> tuple[str, ...]:
    path.write_text(
        """
import sys
from pathlib import Path
from PIL import Image, ImageDraw
if '--version' in sys.argv:
    print('0.47.0')
    raise SystemExit(0)
width = int(sys.argv[sys.argv.index('--width') + 1])
height = int(sys.argv[sys.argv.index('--height') + 1])
output = Path(sys.argv[-1])
scale = width / 128
image = Image.new('RGBA', (width, height), (0, 0, 0, 0))
draw = ImageDraw.Draw(image)
draw.ellipse(tuple(int(v * scale) for v in (8, 8, 120, 120)), fill='#7c3aed')
draw.ellipse(tuple(int(v * scale) for v in (36, 36, 92, 92)), fill=(0, 0, 0, 0))
image.save(output)
""".strip()
        + "\n",
        encoding="utf-8",
    )
    return (active_python_executable(), str(path))


def adapters(tmp_path: Path) -> tuple[VTracerAdapter, PotraceAdapter, ResvgAdapter]:
    vtracer_lock = load_vtracer_lock(CONFIGS / "vtracer.lock.json", "windows-x86_64")
    potrace_lock = load_potrace_lock(CONFIGS / "potrace.lock.json", "windows-x86_64")
    executable_sha = file_sha256(Path(active_python_executable()))
    return (
        VTracerAdapter(
            presets=vtracer_lock.presets,
            command_prefix=write_fake_vectorizer(
                tmp_path / "fake_vtracer.py", vtracer_lock.version_output, "vtracer"
            ),
            expected_version_output=vtracer_lock.version_output,
            expected_executable_sha256=executable_sha,
        ),
        PotraceAdapter(
            presets=potrace_lock.presets,
            command_prefix=write_fake_vectorizer(
                tmp_path / "fake_potrace.py", potrace_lock.version_output, "potrace"
            ),
            expected_version_output=potrace_lock.version_output,
            expected_executable_sha256=executable_sha,
        ),
        ResvgAdapter(
            command_prefix=write_fake_resvg(tmp_path / "fake_resvg.py"),
            expected_version_output="0.47.0",
            expected_executable_sha256=executable_sha,
        ),
    )


def test_smoke_benchmark_runs_two_baselines_and_is_repeatable(tmp_path: Path) -> None:
    vtracer, potrace, renderer = adapters(tmp_path)
    first = run_smoke_benchmark(
        tmp_path / "run-a",
        vtracer=vtracer,
        potrace=potrace,
        renderer=renderer,
    )
    second = run_smoke_benchmark(
        tmp_path / "run-b",
        vtracer=vtracer,
        potrace=potrace,
        renderer=renderer,
    )
    verify_repeatability(first, second)
    assert first.all_baselines_succeeded
    assert len(first.report.summaries) == 2
    assert set(first.artifact_sha256) == {
        "potrace.png",
        "potrace.svg",
        "vtracer.png",
        "vtracer.svg",
    }
    assert (tmp_path / "run-a" / "benchmark-report.json").is_file()
    assert (tmp_path / "run-a" / "benchmark-report.html").is_file()
