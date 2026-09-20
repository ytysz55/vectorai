"""Generate deterministic T0-T3 variants for a procedural dataset."""

from __future__ import annotations

import argparse
from pathlib import Path

from vectorai_bench.degradation import generate_degraded_variants
from vectorai_bench.manifest import manifest_sha256

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATASET = ROOT / "datasets" / "generated" / "procedural-e1-v1"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    args = parser.parse_args()
    try:
        manifest = generate_degraded_variants(args.dataset)
    except (OSError, ValueError) as error:
        print(f"cannot generate degraded variants: {error}")
        return 1
    print(f"generated {len(manifest.cases)} variants: {manifest_sha256(manifest)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
