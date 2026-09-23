"""Run the E5 deterministic optimizer Gate G4 ablation."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any, cast

from vectorai_bench.optimizer_gate import run_optimizer_gate

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ROOT / "benchmark" / "reports" / "optimizer-g4"
DEFAULT_PROFILES = ROOT / "benchmark" / "configs" / "optimizer-profiles-v1.json"


def _resvg(value: str | None) -> Path:
    resolved = value or shutil.which("resvg")
    if resolved is None:
        raise ValueError("resvg executable is required")
    return Path(resolved)


def _report(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"cannot read optimizer G4 report: {error}") from error
    if not isinstance(payload, dict):
        raise RuntimeError("optimizer G4 report must be an object")
    return cast(dict[str, Any], payload)


def _run(output: Path, resvg: Path, profiles: Path) -> tuple[bool, str]:
    evaluation = run_optimizer_gate(
        output,
        resvg_executable=resvg,
        profile_path=profiles,
    )
    report = _report(output / "g4-report.json")
    print(
        f"G4 {'PASSED' if evaluation.passed else 'FAILED'}: "
        f"topology={evaluation.exact_topology_rate:.1%}, "
        f"mean_fidelity_gain={evaluation.mean_fidelity_improvement:.6f}, "
        f"median_node_advantage={evaluation.median_node_advantage:.1%}, "
        f"runtime_p95={evaluation.optimized_runtime_p95_ms:.1f}ms"
    )
    return evaluation.passed, str(report["semantic_digest"])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--resvg")
    parser.add_argument("--profiles", type=Path, default=DEFAULT_PROFILES)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--verify-repeat", action="store_true")
    args = parser.parse_args()
    try:
        passed, first_digest = _run(args.output, _resvg(args.resvg), args.profiles)
        if args.verify_repeat:
            repeat = args.output.with_name(f"{args.output.name}-repeat")
            repeat_passed, second_digest = _run(repeat, _resvg(args.resvg), args.profiles)
            passed = passed and repeat_passed
            if first_digest != second_digest:
                raise RuntimeError(
                    f"optimizer semantic digest mismatch: {first_digest} != {second_digest}"
                )
    except (OSError, RuntimeError, ValueError, KeyError, TypeError) as error:
        print(f"optimizer G4 benchmark failed to run: {error}")
        return 1
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
