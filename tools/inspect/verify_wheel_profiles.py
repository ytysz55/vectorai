"""Verify the pinned offline optimizer resource in a built wheel, not the source tree."""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[2]
RESOURCE = "vectorai_engine/optimizer-profiles-v1.json"


def verify_wheel(wheel: Path) -> None:
    expected = (ROOT / "benchmark/configs/optimizer-profiles-v1.json").read_bytes()
    with ZipFile(wheel) as archive:
        if archive.namelist().count(RESOURCE) != 1:
            raise ValueError("wheel must contain exactly one pinned optimizer profile resource")
        payload = archive.read(RESOURCE)
        if payload != expected:
            raise ValueError("packaged optimizer profiles differ from the locked benchmark")
        with tempfile.TemporaryDirectory(prefix="vectorai-wheel-check-") as location:
            destination = Path(location)
            for entry in archive.infolist():
                target = (destination / entry.filename).resolve()
                if not target.is_relative_to(destination.resolve()):
                    raise ValueError("wheel entry escapes temporary inspection root")
            archive.extractall(destination)
            environment = {**os.environ, "PYTHONPATH": str(destination)}
            result = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    "from vectorai_engine.profiles import "
                    "OPTIMIZER_PROFILE_PATH, OptimizationMode, load_optimizer_profiles; "
                    "assert OPTIMIZER_PROFILE_PATH.is_file(); "
                    "assert load_optimizer_profiles(OPTIMIZER_PROFILE_PATH)"
                    ".select(OptimizationMode.FAITHFUL).mode is OptimizationMode.FAITHFUL",
                ],
                cwd=destination,
                env=environment,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            if result.returncode:
                raise ValueError("unpacked wheel cannot load offline optimizer profiles")
    print(f"wheel optimizer profiles verified: {hashlib.sha256(payload).hexdigest()}")


def main() -> int:
    if len(sys.argv) != 2:
        raise ValueError("usage: verify_wheel_profiles.py <wheel-directory>")
    directory = Path(sys.argv[1])
    wheels = list(directory.glob("vectorai_tools-*.whl"))
    if len(wheels) != 1:
        raise ValueError("expected exactly one VectorAI wheel in the distribution directory")
    verify_wheel(wheels[0])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
