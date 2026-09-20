"""Generate deterministic E1 procedural benchmark fixtures."""

from __future__ import annotations

import argparse
from pathlib import Path

from vectorai_bench.fixtures import generate_fixture_set
from vectorai_bench.manifest import manifest_sha256

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ROOT / "datasets" / "generated" / "procedural-e1-v1"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    try:
        manifest = generate_fixture_set(args.output)
    except OSError as error:
        print(f"cannot generate fixtures: {error}")
        return 1
    print(f"generated {len(manifest.cases)} cases: {manifest_sha256(manifest)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
