"""Build deterministic JSON and HTML benchmark reports."""

from __future__ import annotations

import argparse
from pathlib import Path

from vectorai_bench.reporting import build_report, load_records, write_report

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ROOT / "benchmark" / "reports"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("records", type=Path)
    parser.add_argument("--dataset-sha256", required=True)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    try:
        report = build_report(load_records(args.records), dataset_sha256=args.dataset_sha256)
        write_report(
            report,
            args.output / "benchmark-report.json",
            args.output / "benchmark-report.html",
        )
    except ValueError as error:
        print(f"cannot generate benchmark report: {error}")
        return 1
    print(f"report contains {len(report.summaries)} runner summaries")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
