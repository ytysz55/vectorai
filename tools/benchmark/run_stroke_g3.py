"""Run the E4 deterministic Stroke Gate G3 benchmark."""

from __future__ import annotations

import argparse
import json
import platform
import shutil
from pathlib import Path
from typing import Any, cast

from vectorai_bench.renderers import ResvgAdapter, load_resvg_release
from vectorai_bench.stroke_gate import run_stroke_gate

ROOT = Path(__file__).resolve().parents[2]
CONFIGS = ROOT / "benchmark" / "configs"
DEFAULT_OUTPUT = ROOT / "benchmark" / "reports" / "stroke-g3"


def platform_key() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()
    if machine not in {"x86_64", "amd64"}:
        raise ValueError(f"unsupported stroke architecture: {machine}")
    if system == "windows":
        return "windows-x86_64"
    if system == "linux":
        return "linux-x86_64"
    raise ValueError(f"unsupported stroke platform: {system}")


def executable(value: str | None, name: str) -> Path:
    resolved = value or shutil.which(name)
    if resolved is None:
        raise ValueError(f"{name} executable is required")
    return Path(resolved)


def _load_report(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"cannot read stroke G3 report: {error}") from error
    if not isinstance(payload, dict):
        raise RuntimeError("stroke G3 report root must be an object")
    return cast(dict[str, Any], payload)


def _run(output: Path, resvg_path: Path, renderer: ResvgAdapter) -> str:
    evaluation = run_stroke_gate(
        output,
        resvg_executable=resvg_path,
        renderer=renderer,
    )
    report = _load_report(output / "g3-report.json")
    print(
        f"G3 {'PASSED' if evaluation.passed else 'FAILED'}: "
        f"routing={evaluation.routing_accuracy:.1%}, "
        f"connectivity={evaluation.connectivity_accuracy:.1%}, "
        f"centerline_p95={evaluation.maximum_centerline_p95}, "
        f"node_advantage={evaluation.node_advantage_vs_fill}"
    )
    return str(report["semantic_digest"])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--resvg")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--verify-repeat", action="store_true")
    args = parser.parse_args()
    try:
        key = platform_key()
        release = load_resvg_release(CONFIGS / "resvg.lock.json", key)
        resvg_path = executable(args.resvg, "resvg")
        renderer = ResvgAdapter(
            executable=resvg_path,
            expected_version_output=release.version_output,
            expected_executable_sha256=release.executable_sha256,
        )
        first_digest = _run(args.output, resvg_path, renderer)
        report = _load_report(args.output / "g3-report.json")
        evaluation_payload = report.get("evaluation")
        if not isinstance(evaluation_payload, dict):
            raise RuntimeError("stroke G3 report evaluation must be an object")
        passed_value = evaluation_payload.get("passed")
        if not isinstance(passed_value, bool):
            raise RuntimeError("stroke G3 report passed value must be boolean")
        passed = passed_value
        if args.verify_repeat:
            repeat = args.output.with_name(f"{args.output.name}-repeat")
            second_digest = _run(repeat, resvg_path, renderer)
            if first_digest != second_digest:
                raise RuntimeError(
                    f"stroke semantic digest mismatch: {first_digest} != {second_digest}"
                )
    except (OSError, RuntimeError, ValueError, KeyError, TypeError) as error:
        print(f"stroke G3 benchmark failed to run: {error}")
        return 1
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
