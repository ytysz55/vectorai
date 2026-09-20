"""Minimal E0 CLI entry point."""

from __future__ import annotations

import argparse
import json
import platform
import sys
from collections.abc import Sequence
from pathlib import Path

from vectorai_cli import __version__
from vectorai_engine import BinaryPipelineConfig, EngineFailure, run_binary_pipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="vectorai")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("doctor", help="print the local foundation environment")
    vectorize = subparsers.add_parser("vectorize", help="run the E2 binary vectorizer")
    vectorize.add_argument("input", type=Path)
    vectorize.add_argument("--output-dir", type=Path, required=True)
    vectorize.add_argument("--native-executable", type=Path, required=True)
    vectorize.add_argument("--resvg-executable", type=Path)
    vectorize.add_argument("--threshold", type=float)
    vectorize.add_argument("--no-subpixel", action="store_true")
    vectorize.add_argument("--bezier-only", action="store_true")
    vectorize.add_argument("--timeout-seconds", type=float, default=60.0)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "doctor":
        print(
            json.dumps(
                {
                    "vectorai_version": __version__,
                    "python_version": platform.python_version(),
                    "platform": platform.system().lower(),
                    "machine": platform.machine().lower(),
                },
                sort_keys=True,
            )
        )
        return 0

    if args.command == "vectorize":
        try:
            bundle = run_binary_pipeline(
                args.input,
                args.output_dir,
                BinaryPipelineConfig(
                    native_executable=args.native_executable,
                    resvg_executable=args.resvg_executable,
                    threshold=args.threshold,
                    subpixel=not args.no_subpixel,
                    bezier_only=args.bezier_only,
                    timeout_seconds=args.timeout_seconds,
                ),
            )
        except EngineFailure as failure:
            print(
                json.dumps(
                    {
                        "code": failure.error.code.value,
                        "stage": failure.error.stage.value,
                        "message": failure.error.message,
                        "retryable": failure.error.retryable,
                        "entity_ids": list(failure.error.entity_ids),
                        "context": failure.error.context,
                    },
                    sort_keys=True,
                ),
                file=sys.stderr,
            )
            return 2
        print(
            json.dumps(
                {
                    "status": bundle.final_status.value,
                    "output_directory": str(bundle.output_directory),
                    "svg": str(bundle.svg_path),
                    "manifest": str(bundle.manifest_path),
                    "validation": str(bundle.validation_path),
                },
                sort_keys=True,
            )
        )
        return 0 if bundle.final_status.value != "failed" else 2

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
