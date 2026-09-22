"""Run the native E2 binary CLI twice and verify semantic byte repeatability."""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from pathlib import Path


def write_fixture(path: Path) -> None:
    width = 24
    height = 20
    pixels = bytearray(width * height)
    for y in range(3, 17):
        for x in range(4, 20):
            pixels[y * width + x] = 255
    for y in range(7, 13):
        for x in range(9, 15):
            pixels[y * width + x] = 0
    path.write_bytes(f"P5\n{width} {height}\n255\n".encode() + pixels)


def run_once(native: Path, fixture: Path, directory: Path) -> tuple[bytes, bytes]:
    directory.mkdir()
    svg = directory / "output.svg"
    report = directory / "report.json"
    completed = subprocess.run(
        (
            str(native.resolve()),
            "--input",
            str(fixture.resolve()),
            "--output",
            str(svg.resolve()),
            "--report",
            str(report.resolve()),
            "--subpixel",
            "1",
        ),
        check=False,
        shell=False,
        capture_output=True,
        text=True,
        timeout=30.0,
    )
    if completed.returncode != 0:
        report_detail = ""
        if report.is_file():
            report_text = report.read_text(encoding="utf-8", errors="replace").strip()
            report_detail = f"; report={report_text}"
        process_detail = (completed.stderr or completed.stdout).strip()
        if process_detail:
            process_detail = f"; process={process_detail}"
        raise RuntimeError(
            f"native binary smoke failed with exit code {completed.returncode}"
            f"{report_detail}{process_detail}"
        )
    try:
        report_bytes = report.read_bytes()
        payload = json.loads(report_bytes)
        svg_bytes = svg.read_bytes()
        if payload["components"] != 1 or payload["holes"] != 1 or payload["euler"] != 0:
            raise RuntimeError(f"unexpected topology: {payload}")
        if payload["selected_shapes"] != 2 or payload["segments"] < 8:
            raise RuntimeError(f"unexpected vector model: {payload}")
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as error:
        raise RuntimeError(f"invalid native smoke artifacts: {error}") from error
    return svg_bytes, report_bytes


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--native", type=Path, required=True)
    args = parser.parse_args()
    if not args.native.is_file():
        parser.error(f"native executable does not exist: {args.native}")
    with tempfile.TemporaryDirectory(prefix="vectorai-native-smoke-") as temporary:
        root = Path(temporary)
        fixture = root / "fixture.pgm"
        write_fixture(fixture)
        first = run_once(args.native, fixture, root / "first")
        second = run_once(args.native, fixture, root / "second")
    if first != second:
        raise RuntimeError("native SVG or semantic report changed across identical runs")
    print(json.dumps({"status": "passed", "svg_bytes": len(first[0])}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
