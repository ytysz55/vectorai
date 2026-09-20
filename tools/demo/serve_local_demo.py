"""Start the VectorAI API and Vite review UI with one local-only command."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WEB_DIRECTORY = ROOT / "apps" / "web"
API_STARTER = ROOT / "tools" / "demo" / "serve_local_api.py"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--resvg", type=Path)
    parser.add_argument("--resvg-command", nargs="+", help="local resvg command prefix")
    parser.add_argument("--jobs-dir", type=Path, default=Path("out/local-api-jobs"))
    args = parser.parse_args()
    if args.resvg is None and not args.resvg_command:
        parser.error("--resvg or --resvg-command is required")
    if not (WEB_DIRECTORY / "node_modules" / "vite").is_dir():
        parser.error("install the web dependencies first: cd apps/web && npm install")
    api_command = [
        sys.executable,
        str(API_STARTER),
        "--jobs-dir",
        str(args.jobs_dir),
        "--port",
        "8000",
    ]
    if args.resvg_command:
        api_command.extend(("--resvg-command", *args.resvg_command))
    else:
        api_command.extend(("--resvg", str(args.resvg)))
    vite_entrypoint = WEB_DIRECTORY / "node_modules" / "vite" / "bin" / "vite.js"
    api: subprocess.Popen[bytes] | None = None
    vite: subprocess.Popen[bytes] | None = None
    try:
        vite = subprocess.Popen(
            ("node", str(vite_entrypoint), "--host", "127.0.0.1"),
            cwd=WEB_DIRECTORY,
        )
        api = subprocess.Popen(api_command, cwd=ROOT)
        return api.wait()
    except KeyboardInterrupt:
        return 0
    finally:
        for process in (api, vite):
            if process is not None and process.poll() is None:
                process.terminate()
                process.wait(timeout=10.0)


if __name__ == "__main__":
    raise SystemExit(main())
