"""Serve the VectorAI demo API on a loopback interface only."""

from __future__ import annotations

import argparse
from pathlib import Path

import uvicorn  # type: ignore[import-not-found, unused-ignore]

from vectorai_api.app import ApiSettings, create_app


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--resvg", type=Path)
    parser.add_argument("--resvg-command", nargs="+", help="local resvg command prefix")
    parser.add_argument("--jobs-dir", type=Path, default=Path("out/local-api-jobs"))
    parser.add_argument("--max-queued-jobs", type=int, default=2)
    parser.add_argument("--max-parallel-uploads", type=int, default=3)
    parser.add_argument("--job-timeout-seconds", type=float, default=180.0)
    parser.add_argument("--host", choices=("127.0.0.1", "::1"), default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("port must be in [1, 65535]")
    if args.resvg is None and not args.resvg_command:
        parser.error("--resvg or --resvg-command is required")
    if not 0 <= args.max_queued_jobs <= 16:
        parser.error("--max-queued-jobs must be in [0, 16]")
    if not 1 <= args.max_parallel_uploads <= 16:
        parser.error("--max-parallel-uploads must be in [1, 16]")
    if not 0 < args.job_timeout_seconds <= 3600:
        parser.error("--job-timeout-seconds must be in (0, 3600]")
    app = create_app(
        ApiSettings(
            jobs_directory=args.jobs_dir,
            resvg_executable=args.resvg,
            resvg_command_prefix=tuple(args.resvg_command) if args.resvg_command else None,
            max_queued_jobs=args.max_queued_jobs,
            max_parallel_uploads=args.max_parallel_uploads,
            max_job_seconds=args.job_timeout_seconds,
        )
    )
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
