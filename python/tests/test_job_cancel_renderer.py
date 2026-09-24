from __future__ import annotations

import subprocess
import time
from contextlib import suppress
from pathlib import Path

import psutil  # type: ignore[import-untyped]
from python.tests._support import active_python_executable
from python.tests.test_local_api import image_bytes, request, unused_port, wait_ready

ROOT = Path(__file__).resolve().parents[2]


def test_cancel_running_job_kills_renderer_descendant(tmp_path: Path) -> None:
    script = tmp_path / "stall_renderer.py"
    script.write_text(
        "import os, sys, time\n"
        "from pathlib import Path\n"
        "if '--version' in sys.argv:\n"
        "    print('fake-resvg 1.0')\n"
        "    raise SystemExit(0)\n"
        "Path(__file__).with_suffix('.marker').write_text(str(os.getpid()))\n"
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
            "--jobs-dir",
            str(tmp_path / "jobs"),
            "--port",
            str(port),
        ),
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    renderer_pid: int | None = None
    try:
        wait_ready(base)
        status, body, _ = request(
            f"{base}/v1/jobs",
            body=image_bytes(),
            headers={"content-type": "image/png"},
        )
        assert status == 202
        import json

        job_id = json.loads(body)["job_id"]
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline and not marker.is_file():
            time.sleep(0.05)
        assert marker.is_file(), "worker did not reach the renderer"
        renderer_pid = int(marker.read_text(encoding="utf-8"))
        assert psutil.pid_exists(renderer_pid)
        status, _, _ = request(f"{base}/v1/jobs/{job_id}/cancel", method="POST", body=b"")
        assert status == 200
        state = "running"
        while time.monotonic() < deadline:
            status, body, _ = request(f"{base}/v1/jobs/{job_id}")
            assert status == 200
            state = json.loads(body)["state"]
            if state == "canceled" and not psutil.pid_exists(renderer_pid):
                break
            time.sleep(0.05)
        assert state == "canceled"
        assert not psutil.pid_exists(renderer_pid), "renderer subprocess was orphaned"
        assert not (tmp_path / "jobs" / job_id / "artifacts" / "output.svg").exists()
    finally:
        process.terminate()
        process.wait(timeout=10)
        if renderer_pid is not None:
            with suppress(psutil.NoSuchProcess, psutil.AccessDenied):
                psutil.Process(renderer_pid).kill()
