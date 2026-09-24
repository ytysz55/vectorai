"""Assemble schema-valid E6 release evidence from locked G2/G3/G4 runs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, cast

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

from vectorai_bench.release_gate import build_e6_release_report

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROOT / "schemas" / "e6-release-report.schema.json"


def main() -> int:
    parser = argparse.ArgumentParser()
    for gate in ("g2", "g3", "g4"):
        parser.add_argument(f"--{gate}-dir", required=True, type=Path)
        parser.add_argument(f"--{gate}-repeat", required=True, type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--renderer-rmse-limit", type=float, default=0.08)
    args = parser.parse_args()
    try:
        if args.output.exists():
            raise ValueError("E6 output file already exists")
        report = build_e6_release_report(
            args.g2_dir,
            args.g3_dir,
            args.g4_dir,
            g2_repeat=args.g2_repeat,
            g3_repeat=args.g3_repeat,
            g4_repeat=args.g4_repeat,
            renderer_rmse_limit=args.renderer_rmse_limit,
        )
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        cast(Any, Draft202012Validator(schema)).validate(report)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        raw_evaluation = report["evaluation"]
        if not isinstance(raw_evaluation, dict):
            raise ValueError("E6 evaluation is missing")
        evaluation = cast(dict[str, object], raw_evaluation)
        passed = evaluation.get("passed")
        pair_count = evaluation.get("renderer_pair_count")
        maximum = evaluation.get("maximum_renderer_rmse")
        if (
            not isinstance(passed, bool)
            or not isinstance(pair_count, int)
            or not isinstance(maximum, (int, float))
        ):
            raise ValueError("E6 evaluation fields are invalid")
        print(
            f"E6 {'PASSED' if passed else 'FAILED'}: "
            f"renderer_pairs={pair_count}, maximum_white_matte_rmse={maximum:.6f}"
        )
        return 0 if passed else 2
    except (OSError, ValueError, TypeError, KeyError) as error:
        print(f"E6 release evidence failed: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
