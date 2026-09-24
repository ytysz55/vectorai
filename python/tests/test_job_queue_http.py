from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

from python.tests._support import active_python_executable
from python.tests.test_local_api import image_bytes, request, unused_port, wait_ready

ROOT = Path(__file__).resolve().parents[2]


def test_http_idempotency_queue_limit_and_cors(tmp_path: Path) -> None:
    script = tmp_path / "slow_renderer.py"
    script.write_text(
        "import sys, time\n"
        "from pathlib import Path\n"
        "if '--version' in sys.argv:\n"
        "    print('fake-resvg 1.0')\n"
        "    raise SystemExit(0)\n"
        "Path(__file__).with_suffix('.marker').write_text('started')\n"
        "time.sleep(30)\n",
        encoding="utf-8",
    )
    marker = script.with_suffix(".marker")
    port = unused_port()
    base = f"http://127.0.0.1:{port}"
    process = subprocess.Popen(
        (
            active_python_executable(),
            "tools/demo/serve_local_api.py",
            "--resvg-command",
            active_python_executable(),
            str(script),
            "--max-queued-jobs",
            "1",
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
        cors, _, response_headers = request(
            f"{base}/v1/jobs",
            method="OPTIONS",
            headers={
                "origin": "http://127.0.0.1:5173",
                "access-control-request-method": "POST",
                "access-control-request-headers": "idempotency-key",
            },
        )
        assert cors == 200
        assert "idempotency-key" in response_headers["access-control-allow-headers"].lower()
        headers = {"content-type": "image/png", "idempotency-key": "request-A"}
        first_code, body, _ = request(f"{base}/v1/jobs", body=image_bytes(), headers=headers)
        assert first_code == 202
        first = json.loads(body)
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline and not marker.exists():
            time.sleep(0.05)
        assert marker.is_file(), "first job did not reach the renderer"
        repeated_code, body, _ = request(f"{base}/v1/jobs", body=image_bytes(), headers=headers)
        assert repeated_code == 202
        assert json.loads(body)["job_id"] == first["job_id"]
        conflict, body, _ = request(f"{base}/v1/jobs", body=b"changed", headers=headers)
        assert conflict == 409
        assert json.loads(body)["detail"]["code"] == "IDEMPOTENCY_CONFLICT"
        queued_code, body, _ = request(
            f"{base}/v1/jobs",
            body=image_bytes(),
            headers={"content-type": "image/png", "idempotency-key": "request-B"},
        )
        assert queued_code == 202
        queued = json.loads(body)
        assert queued["state"] == "accepted"
        full, body, _ = request(
            f"{base}/v1/jobs",
            body=image_bytes(),
            headers={"content-type": "image/png", "idempotency-key": "request-C"},
        )
        assert full == 429
        assert json.loads(body)["detail"]["code"] == "RESOURCE_LIMIT"
        canceled, body, _ = request(
            f"{base}/v1/jobs/{queued['job_id']}/cancel", method="POST", body=b""
        )
        assert canceled == 200 and json.loads(body)["state"] == "canceled"
        replay, body, _ = request(
            f"{base}/v1/jobs",
            body=image_bytes(),
            headers={"content-type": "image/png", "idempotency-key": "request-B"},
        )
        assert replay == 202 and json.loads(body)["job_id"] == queued["job_id"]
        cancel_running, _, _ = request(
            f"{base}/v1/jobs/{first['job_id']}/cancel", method="POST", body=b""
        )
        assert cancel_running == 200
    finally:
        process.terminate()
        process.wait(timeout=10)
