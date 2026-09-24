"""Isolated single-job process for the loopback E7 API.

Only the API writes public job status; this worker writes a private result record.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import cast

from vectorai_engine.errors import EngineFailure
from vectorai_engine.multicolor_pipeline import MulticolorPipelineConfig, run_multicolor_pipeline
from vectorai_engine.stroke_pipeline import StrokePipelineConfig, run_stroke_pipeline


def _result(path: Path, payload: dict[str, object]) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def run_worker(job_directory: Path) -> int:
    target = job_directory / "worker-result.json"
    try:
        settings = json.loads((job_directory / "worker-config.json").read_text(encoding="utf-8"))
        if not isinstance(settings, dict):
            raise ValueError("worker configuration must be an object")
        data = cast(dict[str, object], settings)
        mode = data.get("mode")
        name = data.get("input_name")
        executable = data.get("resvg_executable")
        prefix = data.get("resvg_command_prefix")
        if (
            not isinstance(mode, str)
            or mode not in {"geometric", "stroke"}
            or not isinstance(name, str)
            or name not in {"input.png", "input.jpg"}
        ):
            raise ValueError("unsupported job configuration")
        if executable is not None and not isinstance(executable, str):
            raise ValueError("invalid renderer executable")
        if prefix is not None and (
            not isinstance(prefix, list)
            or not prefix
            or not all(isinstance(item, str) for item in cast(list[object], prefix))
        ):
            raise ValueError("invalid renderer command")
        command = tuple(cast(list[str], prefix)) if prefix is not None else None
        renderer = Path(executable) if isinstance(executable, str) else None
        source = job_directory / name
        output = job_directory / "artifacts"
        if mode == "stroke":
            stroke_bundle = run_stroke_pipeline(
                source,
                output,
                StrokePipelineConfig(resvg_executable=renderer, resvg_command_prefix=command),
            )
            scene = json.loads(stroke_bundle.scene_path.read_text(encoding="utf-8"))
            palette_count = 1
            region_count = scene["graph"]["component_count"]
            seam_gap_rate = 0.0
            status = stroke_bundle.final_status.value
        else:
            multicolor_bundle = run_multicolor_pipeline(
                source,
                output,
                MulticolorPipelineConfig(resvg_executable=renderer, resvg_command_prefix=command),
            )
            scene = json.loads(multicolor_bundle.scene_path.read_text(encoding="utf-8"))
            manifest = json.loads(multicolor_bundle.manifest_path.read_text(encoding="utf-8"))
            palette_count = scene["palette"]["selected_color_count"]
            region_count = scene["segmentation"]["region_count"]
            seam_gap_rate = max(
                (item["transparent_gap_rate"] for item in manifest["seams"]["observations"]),
                default=0.0,
            )
            status = multicolor_bundle.final_status.value
        _result(
            target,
            {
                "state": status,
                "palette_count": palette_count,
                "region_count": region_count,
                "seam_gap_rate": seam_gap_rate,
            },
        )
        return 0
    except EngineFailure as failure:
        _result(
            target,
            {
                "state": "failed",
                "error": {
                    "code": failure.error.code.value,
                    "stage": failure.error.stage.value,
                    "message": "Local reconstruction failed; inspect validation if available.",
                    "retryable": failure.error.retryable,
                },
            },
        )
        return 1
    except (OSError, ValueError, KeyError, TypeError, IndexError):
        _result(
            target,
            {
                "state": "failed",
                "error": {
                    "code": "INTERNAL_INVARIANT_VIOLATION",
                    "stage": "unknown",
                    "message": "Local job failed without a validated output.",
                    "retryable": False,
                },
            },
        )
        return 1


def main() -> int:
    if len(sys.argv) != 2:
        return 2
    return run_worker(Path(sys.argv[1]))


if __name__ == "__main__":
    raise SystemExit(main())
