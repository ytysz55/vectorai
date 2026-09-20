"""Run the one-seed/two-baseline E1 smoke benchmark."""

from __future__ import annotations

import argparse
import platform
import shutil
from pathlib import Path

from vectorai_bench.baselines import (
    PotraceAdapter,
    VTracerAdapter,
    load_potrace_lock,
    load_vtracer_lock,
)
from vectorai_bench.renderers import ResvgAdapter, load_resvg_release
from vectorai_bench.smoke import run_smoke_benchmark, verify_repeatability

ROOT = Path(__file__).resolve().parents[2]
CONFIGS = ROOT / "benchmark" / "configs"
DEFAULT_OUTPUT = ROOT / "benchmark" / "reports" / "smoke"


def platform_key() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()
    if machine not in {"x86_64", "amd64"}:
        raise ValueError(f"unsupported smoke architecture: {machine}")
    if system == "windows":
        return "windows-x86_64"
    if system == "linux":
        return "linux-x86_64"
    raise ValueError(f"unsupported smoke platform: {system}")


def executable_path(value: str | None, name: str) -> Path | None:
    resolved = value or shutil.which(name)
    return Path(resolved) if resolved else None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vtracer")
    parser.add_argument("--potrace")
    parser.add_argument("--resvg")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--verify-repeat", action="store_true")
    args = parser.parse_args()
    try:
        key = platform_key()
        vtracer_lock = load_vtracer_lock(CONFIGS / "vtracer.lock.json", key)
        potrace_lock = load_potrace_lock(CONFIGS / "potrace.lock.json", key)
        resvg_lock = load_resvg_release(CONFIGS / "resvg.lock.json", key)
        vtracer = VTracerAdapter(
            presets=vtracer_lock.presets,
            executable=executable_path(args.vtracer, "vtracer"),
            expected_version_output=vtracer_lock.version_output,
            expected_executable_sha256=vtracer_lock.executable_sha256,
        )
        potrace = PotraceAdapter(
            presets=potrace_lock.presets,
            executable=executable_path(args.potrace, "potrace"),
            expected_version_output=potrace_lock.version_output,
            expected_executable_sha256=potrace_lock.executable_sha256,
        )
        renderer = ResvgAdapter(
            executable=executable_path(args.resvg, "resvg"),
            expected_version_output=resvg_lock.version_output,
            expected_executable_sha256=resvg_lock.executable_sha256,
        )
        if args.verify_repeat:
            first = run_smoke_benchmark(
                args.output / "run-a",
                vtracer=vtracer,
                potrace=potrace,
                renderer=renderer,
            )
            second = run_smoke_benchmark(
                args.output / "run-b",
                vtracer=vtracer,
                potrace=potrace,
                renderer=renderer,
            )
            verify_repeatability(first, second)
            result = first
        else:
            result = run_smoke_benchmark(
                args.output,
                vtracer=vtracer,
                potrace=potrace,
                renderer=renderer,
            )
    except (OSError, ValueError, RuntimeError) as error:
        print(f"smoke benchmark failed: {error}")
        return 1
    if not result.all_baselines_succeeded:
        print("smoke benchmark recorded one or more failed/unsupported baselines")
        return 1
    print(f"smoke semantic digest: {result.semantic_records_sha256}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
