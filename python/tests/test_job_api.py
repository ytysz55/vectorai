from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Any, cast

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]
from python.tests._support import active_python_executable
from python.tests.test_local_api import (
    fake_resvg,
    image_bytes,
    request,
    stroke_image_bytes,
    unused_port,
    wait_ready,
)

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = json.loads((ROOT / "schemas/local-job.schema.json").read_text(encoding="utf-8"))
TERMINAL = {"success", "degraded", "needs_review", "unsupported", "failed", "canceled"}


def _validate(payload: object) -> None:
    cast(Any, Draft202012Validator(SCHEMA)).validate(payload)


def _poll(base: str, job_id: str, *, target: set[str], seconds: float = 25.0) -> dict[str, Any]:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        status, body, _ = request(f"{base}/v1/jobs/{job_id}")
        assert status == 200
        payload = json.loads(body)
        if payload["state"] in target:
            return cast(dict[str, Any], payload)
        time.sleep(0.05)
    raise AssertionError(f"job did not reach {sorted(target)}")


def test_job_upload_status_cancel_and_artifact_contract(tmp_path: Path) -> None:
    port = unused_port()
    base = f"http://127.0.0.1:{port}"
    script = fake_resvg(tmp_path / "fake_resvg.py")
    process = subprocess.Popen(
        (
            active_python_executable(),
            "tools/demo/serve_local_api.py",
            "--resvg-command",
            active_python_executable(),
            str(script),
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
        headers = {"content-type": "image/png", "x-vectorai-filename": "logo.png"}
        status, body, _ = request(f"{base}/v1/jobs", body=image_bytes(), headers=headers)
        assert status == 202
        initial = json.loads(body)
        _validate(initial)
        job_id = initial["job_id"]
        assert initial["mode"] == "geometric"
        assert initial["artifacts"] == {}
        final = _poll(base, job_id, target=TERMINAL)
        assert final["state"] == "success", final
        _validate(final)
        assert final["engine_build_id"].startswith("python-")
        assert "output.svg" in final["artifacts"]
        assert "cut-outline.svg" not in final["artifacts"]
        artifact_status, svg, _ = request(f"{base}{final['artifacts']['output.svg']}")
        assert artifact_status == 200 and b"<svg" in svg
        manifest_status, manifest_body, _ = request(
            f"{base}{final['artifacts']['run-manifest.json']}"
        )
        assert manifest_status == 200
        resources = json.loads(manifest_body)["resources"]
        assert resources["total_duration_ms"] >= 0
        assert resources["peak_rss_mb"] >= 0
        secret = tmp_path / "private.svg"
        secret.write_text("private", encoding="utf-8")
        output = tmp_path / "jobs" / job_id / "artifacts" / "output.svg"
        output.unlink()
        try:
            output.symlink_to(secret)
        except OSError:
            pass  # Windows may require Developer Mode for test symlinks.
        else:
            unsafe_status, _, _ = request(f"{base}{final['artifacts']['output.svg']}")
            assert unsafe_status == 404
        cancel_status, _, _ = request(f"{base}/v1/jobs/{job_id}/cancel", method="POST", body=b"")
        assert cancel_status == 409
        missing_status, _, _ = request(f"{base}/v1/jobs/../escape")
        assert missing_status == 404
        unsupported, body, _ = request(
            f"{base}/v1/jobs",
            body=image_bytes(),
            headers={**headers, "x-vectorai-mode": "faithful"},
        )
        assert unsupported == 400
        assert json.loads(body)["detail"]["code"] == "UNSUPPORTED_INPUT"
        oversized, body, _ = request(
            f"{base}/v1/jobs",
            body=b"x",
            headers={"content-type": "image/png", "content-length": str(33 * 1024 * 1024)},
        )
        assert oversized == 413
        assert json.loads(body)["detail"]["code"] == "RESOURCE_LIMIT"
        stroke_status, body, _ = request(
            f"{base}/v1/jobs",
            body=stroke_image_bytes(),
            headers={"content-type": "image/png", "x-vectorai-mode": "stroke"},
        )
        assert stroke_status == 202
        stroke = _poll(base, json.loads(body)["job_id"], target=TERMINAL)
        assert stroke["state"] in {"success", "needs_review", "degraded"}, stroke
        assert "cut-outline.svg" in stroke["artifacts"]
        _validate(stroke)
        invalid, body, _ = request(f"{base}/v1/jobs", body=b"not an image", headers=headers)
        assert invalid == 202
        failed = _poll(base, json.loads(body)["job_id"], target=TERMINAL)
        assert failed["state"] == "failed"
        assert failed["error"]["code"] in {"DECODE_ERROR", "UNSUPPORTED_INPUT"}
        assert "input.png" not in failed["error"]["message"]
        _validate(failed)
    finally:
        process.terminate()
        process.wait(timeout=10)


def test_running_job_cancel_kills_worker_and_releases_slot(tmp_path: Path) -> None:
    port = unused_port()
    base = f"http://127.0.0.1:{port}"
    script = fake_resvg(tmp_path / "fake_resvg.py")
    process = subprocess.Popen(
        (
            active_python_executable(),
            "tools/demo/serve_local_api.py",
            "--resvg-command",
            active_python_executable(),
            str(script),
            "--jobs-dir",
            str(tmp_path / "jobs"),
            "--max-queued-jobs",
            "0",
            "--port",
            str(port),
        ),
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        wait_ready(base)
        headers = {"content-type": "image/png"}
        status, body, _ = request(f"{base}/v1/jobs", body=image_bytes(), headers=headers)
        assert status == 202
        job_id = json.loads(body)["job_id"]
        _poll(base, job_id, target={"running"})
        busy, busy_body, _ = request(f"{base}/v1/jobs", body=image_bytes(), headers=headers)
        assert busy == 429 and json.loads(busy_body)["detail"]["code"] == "RESOURCE_LIMIT"
        preview_status, _, _ = request(f"{base}/v1/jobs/{job_id}/artifacts/preview.png")
        assert preview_status == 404
        canceled, _, _ = request(f"{base}/v1/jobs/{job_id}/cancel", method="POST", body=b"")
        assert canceled == 200
        final = _poll(base, job_id, target=TERMINAL)
        assert final["state"] == "canceled"
        assert final["artifacts"] == {}
        _validate(final)
        status, body, _ = request(f"{base}/v1/jobs", body=image_bytes(), headers=headers)
        assert status == 202
        resumed = _poll(base, json.loads(body)["job_id"], target=TERMINAL)
        assert resumed["state"] == "success", resumed
    finally:
        process.terminate()
        process.wait(timeout=10)
