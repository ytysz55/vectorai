"""Serve the VectorAI demo API on a loopback interface only."""

from __future__ import annotations

import argparse
from pathlib import Path

import uvicorn

from vectorai_api.app import ApiSettings, create_app


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--resvg", type=Path)
    parser.add_argument("--resvg-command", nargs="+", help="local resvg command prefix")
    parser.add_argument("--jobs-dir", type=Path, default=Path("out/local-api-jobs"))
    parser.add_argument("--host", choices=("127.0.0.1", "::1"), default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("port must be in [1, 65535]")
    if args.resvg is None and not args.resvg_command:
        parser.error("--resvg or --resvg-command is required")
    app = create_app(
        ApiSettings(
            jobs_directory=args.jobs_dir,
            resvg_executable=args.resvg,
            resvg_command_prefix=tuple(args.resvg_command) if args.resvg_command else None,
        )
    )
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
