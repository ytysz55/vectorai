"""Run the E2 binary corpus, baselines, ablations, and Gate G1."""

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
from vectorai_bench.e2_gate import run_e2_gate
from vectorai_bench.renderers import ResvgAdapter, load_resvg_release

ROOT = Path(__file__).resolve().parents[2]
CONFIGS = ROOT / "benchmark" / "configs"
DEFAULT_OUTPUT = ROOT / "benchmark" / "reports" / "e2-g1"


def platform_key() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()
    if machine not in {"x86_64", "amd64"}:
        raise ValueError(f"unsupported E2 architecture: {machine}")
    if system == "windows":
        return "windows-x86_64"
    if system == "linux":
        return "linux-x86_64"
    raise ValueError(f"unsupported E2 platform: {system}")


def executable(value: str | None, name: str) -> Path:
    resolved = value or shutil.which(name)
    if resolved is None:
        raise ValueError(f"{name} executable is required")
    return Path(resolved)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--native", required=True)
    parser.add_argument("--vtracer")
    parser.add_argument("--potrace")
    parser.add_argument("--resvg")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--case-count", type=int, default=20)
    args = parser.parse_args()
    try:
        key = platform_key()
        vtracer_lock = load_vtracer_lock(CONFIGS / "vtracer.lock.json", key)
        potrace_lock = load_potrace_lock(CONFIGS / "potrace.lock.json", key)
        resvg_lock = load_resvg_release(CONFIGS / "resvg.lock.json", key)
        vtracer = VTracerAdapter(
            presets=vtracer_lock.presets,
            executable=executable(args.vtracer, "vtracer"),
            expected_version_output=vtracer_lock.version_output,
            expected_executable_sha256=vtracer_lock.executable_sha256,
        )
        potrace = PotraceAdapter(
            presets=potrace_lock.presets,
            executable=executable(args.potrace, "potrace"),
            expected_version_output=potrace_lock.version_output,
            expected_executable_sha256=potrace_lock.executable_sha256,
        )
        renderer = ResvgAdapter(
            executable=executable(args.resvg, "resvg"),
            expected_version_output=resvg_lock.version_output,
            expected_executable_sha256=resvg_lock.executable_sha256,
        )
        evaluation = run_e2_gate(
            args.output,
            native_executable=executable(args.native, "vectorai_binary_cli"),
            resvg_executable=executable(args.resvg, "resvg"),
            vtracer=vtracer,
            potrace=potrace,
            renderer=renderer,
            case_count=args.case_count,
        )
    except (OSError, ValueError, RuntimeError) as error:
        print(f"E2 gate failed to run: {error}")
        return 1
    print(
        f"G1 {'PASSED' if evaluation.passed else 'FAILED'}: "
        f"topology={evaluation.exact_topology_rate:.1%}, "
        f"hard_failures={evaluation.hard_failure_count}, "
        f"node_advantage={evaluation.baseline_node_advantage}"
    )
    return 0 if evaluation.passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
