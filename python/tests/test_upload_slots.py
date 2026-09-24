from __future__ import annotations

import json
import subprocess
import time
from http.client import HTTPConnection
from pathlib import Path

from python.tests._support import active_python_executable
from python.tests.test_local_api import fake_resvg, image_bytes, request, unused_port, wait_ready

ROOT = Path(__file__).resolve().parents[2]


def test_chunked_upload_admission_is_bounded_and_released(tmp_path: Path) -> None:
    port = unused_port()
    base = f"http://127.0.0.1:{port}"
    script = fake_resvg(tmp_path / "resvg.py")
    process = subprocess.Popen(
        (
            active_python_executable(),
            "tools/demo/serve_local_api.py",
            "--resvg-command",
            active_python_executable(),
            str(script),
            "--max-parallel-uploads",
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
    connection = HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        wait_ready(base)
        connection.putrequest("POST", "/v1/jobs")
        connection.putheader("content-type", "image/png")
        connection.putheader("transfer-encoding", "chunked")
        connection.endheaders()
        connection.send(b"4\r\nslow\r\n")
        time.sleep(0.15)
        busy, body, _ = request(
            f"{base}/v1/jobs", body=image_bytes(), headers={"content-type": "image/png"}
        )
        assert busy == 429
        assert json.loads(body)["detail"]["code"] == "RESOURCE_LIMIT"
        connection.send(b"0\r\n\r\n")
        response = connection.getresponse()
        assert response.status == 202
        response.read()
        admitted, _, _ = request(
            f"{base}/v1/jobs", body=image_bytes(), headers={"content-type": "image/png"}
        )
        assert admitted == 202
    finally:
        connection.close()
        process.terminate()
        process.wait(timeout=10)
