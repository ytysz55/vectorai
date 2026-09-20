"""Run the E3 procedural multicolor benchmark and Gate G2 engine checks."""

from __future__ import annotations

import argparse
import platform
import shutil
from pathlib import Path

from vectorai_bench.baselines import VTracerAdapter, load_vtracer_lock
from vectorai_bench.multicolor_gate import run_multicolor_gate
from vectorai_bench.renderers import ResvgAdapter, load_resvg_release

ROOT = Path(__file__).resolve().parents[2]
CONFIGS = ROOT / "benchmark" / "configs"
DEFAULT_OUTPUT = ROOT / "benchmark" / "reports" / "multicolor-g2"


def platform_key() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()
    if machine not in {"x86_64", "amd64"}:
        raise ValueError(f"unsupported multicolor architecture: {machine}")
    if system == "windows":
        return "windows-x86_64"
    if system == "linux":
        return "linux-x86_64"
    raise ValueError(f"unsupported multicolor platform: {system}")


def executable(value: str | None, name: str) -> Path:
    resolved = value or shutil.which(name)
    if resolved is None:
        raise ValueError(f"{name} executable is required")
    return Path(resolved)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vtracer")
    parser.add_argument("--resvg")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    try:
        key = platform_key()
        vtracer_lock = load_vtracer_lock(CONFIGS / "vtracer.lock.json", key)
        resvg_lock = load_resvg_release(CONFIGS / "resvg.lock.json", key)
        vtracer = VTracerAdapter(
            presets=vtracer_lock.presets,
            executable=executable(args.vtracer, "vtracer"),
            expected_version_output=vtracer_lock.version_output,
            expected_executable_sha256=vtracer_lock.executable_sha256,
        )
        resvg_path = executable(args.resvg, "resvg")
        renderer = ResvgAdapter(
            executable=resvg_path,
            expected_version_output=resvg_lock.version_output,
            expected_executable_sha256=resvg_lock.executable_sha256,
        )
        evaluation = run_multicolor_gate(
            args.output,
            resvg_executable=resvg_path,
            vtracer=vtracer,
            renderer=renderer,
        )
    except (OSError, RuntimeError, ValueError) as error:
        print(f"multicolor G2 benchmark failed to run: {error}")
        return 1
    print(
        f"G2 {'PASSED' if evaluation.passed else 'FAILED'}: "
        f"topology={evaluation.exact_topology_rate:.1%}, "
        f"max_seam_gap={evaluation.maximum_seam_gap_rate:.3%}, "
        f"vtracer_node_advantage={evaluation.node_advantage_vs_vtracer}"
    )
    return 0 if evaluation.passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
