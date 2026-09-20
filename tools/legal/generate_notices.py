"""Generate a deterministic third-party notice index from the approved inventory."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INVENTORY = ROOT / "third_party" / "dependencies.json"
DEFAULT_OUTPUT = ROOT / "third_party" / "notices" / "THIRD_PARTY_NOTICES.generated.md"


def load_inventory(path: Path) -> dict[str, Any]:
    try:
        with path.open(encoding="utf-8") as handle:
            payload: dict[str, Any] = json.load(handle)
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot load dependency inventory {path}: {error}") from error
    return payload


def validate_inventory(payload: dict[str, Any], *, release: bool) -> list[str]:
    errors: list[str] = []
    entries = payload.get("entries")
    if not isinstance(entries, list):
        return ["entries must be a list"]

    seen: set[str] = set()
    for index, entry in enumerate(entries):
        prefix = f"entries[{index}]"
        if not isinstance(entry, dict):
            errors.append(f"{prefix} must be an object")
            continue

        for field in ("name", "version", "spdx", "status", "usage", "source_url"):
            if not isinstance(entry.get(field), str) or not entry[field]:
                errors.append(f"{prefix}.{field} must be a non-empty string")

        name = entry.get("name")
        if isinstance(name, str):
            if name in seen:
                errors.append(f"duplicate dependency name: {name}")
            seen.add(name)

        if entry.get("status") not in {"allow", "review", "deny"}:
            errors.append(f"{prefix}.status must be allow, review, or deny")

        if not isinstance(entry.get("distributed"), bool):
            errors.append(f"{prefix}.distributed must be boolean")

        if release and entry.get("distributed"):
            if entry.get("status") != "allow":
                errors.append(f"distributed dependency is not allowed: {name}")
            if entry.get("version") == "not-selected":
                errors.append(f"distributed dependency has no pinned version: {name}")

    return errors


def render_notice_index(payload: dict[str, Any]) -> str:
    entries = sorted(payload["entries"], key=lambda item: item["name"].casefold())
    lines = [
        "# Third-party notice index",
        "",
        "> Generated from `third_party/dependencies.json`; full license texts are required "
        "before distribution.",
        "",
        "| Component | Version | SPDX | Status | Distributed | Source |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for entry in entries:
        distributed = "yes" if entry["distributed"] else "no"
        lines.append(
            f"| {entry['name']} | {entry['version']} | `{entry['spdx']}` | "
            f"{entry['status']} | {distributed} | {entry['source_url']} |"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--release", action="store_true")
    args = parser.parse_args()

    try:
        payload = load_inventory(args.inventory)
    except ValueError as inventory_error:
        print(inventory_error)
        return 1

    errors = validate_inventory(payload, release=args.release)
    if errors:
        for validation_error in errors:
            print(validation_error)
        return 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render_notice_index(payload), encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
