from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from python.tests._support import active_python_executable
from python.tests.test_local_api import fake_resvg, image_bytes, request, unused_port, wait_ready

from vectorai_api import job_worker
from vectorai_engine.errors import RunStatus
from vectorai_engine.multicolor_pipeline import MulticolorPipelineConfig
from vectorai_engine.profiles import (
    OPTIMIZER_PROFILE_PATH,
    OptimizationMode,
    load_optimizer_profiles,
)

ROOT = Path(__file__).resolve().parents[2]
TERMINAL = {"success", "degraded", "needs_review", "unsupported", "failed", "canceled"}


def wait_terminal(base: str, job_id: str) -> dict[str, Any]:
    deadline = time.monotonic() + 25
    while time.monotonic() < deadline:
        code, body, _ = request(f"{base}/v1/jobs/{job_id}")
        assert code == 200
        status: dict[str, Any] = json.loads(body)
        if status["state"] in TERMINAL:
            return status
        time.sleep(0.05)
    raise AssertionError("job did not reach a terminal state")


def test_bundled_profiles_match_the_locked_benchmark_profiles() -> None:
    assert (
        OPTIMIZER_PROFILE_PATH.read_bytes()
        == (ROOT / "benchmark/configs/optimizer-profiles-v1.json").read_bytes()
    )
    profile_set = load_optimizer_profiles(OPTIMIZER_PROFILE_PATH)
    assert (
        profile_set.select(OptimizationMode.FAITHFUL).weights
        != profile_set.select(OptimizationMode.MINIMAL).weights
    )


@pytest.mark.parametrize("mode", ["geometric", "faithful", "minimal"])
def test_job_worker_routes_each_mode_to_the_real_engine_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    configs: list[MulticolorPipelineConfig] = []
    scene = tmp_path / "scene.json"
    scene.write_text(
        json.dumps({"palette": {"selected_color_count": 2}, "segmentation": {"region_count": 2}}),
        encoding="utf-8",
    )
    manifest = tmp_path / "run-manifest.json"
    manifest.write_text(json.dumps({"seams": {"observations": []}}), encoding="utf-8")

    def fake_pipeline(
        _source: Path, _output: Path, config: MulticolorPipelineConfig
    ) -> SimpleNamespace:
        configs.append(config)
        return SimpleNamespace(
            scene_path=scene, manifest_path=manifest, final_status=RunStatus.SUCCESS
        )

    monkeypatch.setattr(job_worker, "run_multicolor_pipeline", fake_pipeline)
    (tmp_path / "input.png").write_bytes(b"input")
    (tmp_path / "worker-config.json").write_text(
        json.dumps(
            {
                "mode": mode,
                "input_name": "input.png",
                "resvg_executable": None,
                "resvg_command_prefix": None,
                "optimizer_profile_path": str(OPTIMIZER_PROFILE_PATH),
            }
        ),
        encoding="utf-8",
    )
    assert job_worker.run_worker(tmp_path) == 0
    assert len(configs) == 1
    assert configs[0].optimizer_mode is OptimizationMode(mode)
    if mode == "geometric":
        assert configs[0].optimizer_profile_path is None
    else:
        assert configs[0].optimizer_profile_path == OPTIMIZER_PROFILE_PATH
    output = cast(dict[str, object], json.loads((tmp_path / "worker-result.json").read_text()))
    assert output["state"] == "success"


def test_http_faithful_and_minimal_use_distinct_pinned_profiles(tmp_path: Path) -> None:
    port = unused_port()
    base = f"http://127.0.0.1:{port}"
    renderer = fake_resvg(tmp_path / "resvg.py")
    process = subprocess.Popen(
        (
            active_python_executable(),
            "tools/demo/serve_local_api.py",
            "--resvg-command",
            active_python_executable(),
            str(renderer),
            "--jobs-dir",
            str(tmp_path / "jobs"),
            "--port",
            str(port),
        ),
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        wait_ready(base)
        profile_hashes: set[str] = set()
        for mode in ("faithful", "minimal"):
            code, body, _ = request(
                f"{base}/v1/jobs",
                body=image_bytes(),
                headers={"content-type": "image/png", "x-vectorai-mode": mode},
            )
            assert code == 202
            job = wait_terminal(base, json.loads(body)["job_id"])
            assert job["state"] == "success", job
            scene_code, scene_body, _ = request(f"{base}{job['artifacts']['scene.json']}")
            assert scene_code == 200
            scene_payload = json.loads(scene_body)
            assert scene_payload["inspection_overlay"]["available"] is True
            optimizer = scene_payload["optimizer"]
            assert optimizer["status"] == "success"
            assert optimizer["mode"] == mode
            profile_hashes.add(optimizer["profile_sha256"])
        assert len(profile_hashes) == 2
    finally:
        process.terminate()
        process.wait(timeout=10)
