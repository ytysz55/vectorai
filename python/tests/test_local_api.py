from __future__ import annotations

import io
import json
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]


def fake_resvg(path: Path) -> Path:
    path.write_text(
        """
import sys
from pathlib import Path
from PIL import Image

if '--version' in sys.argv:
    print('fake-resvg 1.0')
    raise SystemExit(0)
width = int(sys.argv[sys.argv.index('--width') + 1])
height = int(sys.argv[sys.argv.index('--height') + 1])
Image.new('RGBA', (width, height), (0, 0, 0, 255)).save(Path(sys.argv[-1]))
""".strip()
        + "\n",
        encoding="utf-8",
    )
    return path


def image_bytes() -> bytes:
    image = Image.new("RGB", (24, 12))
    for x in range(24):
        color = (220, 30, 30) if x < 12 else (30, 60, 220)
        for y in range(12):
            image.putpixel((x, y), color)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def unused_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as socket_handle:
        socket_handle.bind(("127.0.0.1", 0))
        return int(socket_handle.getsockname()[1])


def request(
    url: str,
    *,
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
    method: str | None = None,
) -> tuple[int, bytes, dict[str, str]]:
    method = method or ("POST" if body is not None else "GET")
    request_object = Request(url, data=body, headers=headers or {}, method=method)
    try:
        with urlopen(request_object, timeout=10.0) as response:
            headers_by_name = {key.lower(): value for key, value in response.headers.items()}
            return response.status, response.read(), headers_by_name
    except HTTPError as error:
        headers_by_name = {key.lower(): value for key, value in error.headers.items()}
        return error.code, error.read(), headers_by_name


def wait_ready(base_url: str) -> None:
    for _ in range(100):
        try:
            status, _, _ = request(f"{base_url}/health")
            if status == 200:
                return
        except OSError:
            pass
        time.sleep(0.05)
    raise AssertionError("local API did not become ready")


def test_loopback_api_vectorizes_and_serves_confined_artifacts(tmp_path: Path) -> None:
    port = unused_port()
    base_url = f"http://127.0.0.1:{port}"
    script = fake_resvg(tmp_path / "fake_resvg.py")
    process = subprocess.Popen(
        (
            sys.executable,
            "tools/demo/serve_local_api.py",
            "--resvg-command",
            sys.executable,
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
        wait_ready(base_url)
        health_status, health_body, _ = request(f"{base_url}/health")
        assert health_status == 200
        assert json.loads(health_body) == {"status": "ready", "local_only": True}
        cors_status, _, cors_headers = request(
            f"{base_url}/v1/vectorize",
            method="OPTIONS",
            headers={
                "origin": "http://127.0.0.1:5173",
                "access-control-request-method": "POST",
            },
        )
        assert cors_status == 200
        assert cors_headers["access-control-allow-origin"] == "http://127.0.0.1:5173"
        status, body, _ = request(
            f"{base_url}/v1/vectorize",
            body=image_bytes(),
            headers={"content-type": "image/png", "x-vectorai-filename": "logo.png"},
        )
        assert status == 200
        payload = json.loads(body)
        assert payload["status"] == "success"
        assert payload["palette_count"] == 2
        assert payload["region_count"] == 2
        svg_status, svg, headers = request(f"{base_url}{payload['artifacts']['output.svg']}")
        assert svg_status == 200
        assert headers["content-type"].startswith("image/svg+xml")
        assert b"<svg" in svg
        escaped_status, _, _ = request(f"{base_url}/v1/jobs/not-a-job/artifacts/../input.png")
        assert escaped_status == 404
        oversized_status, _, _ = request(
            f"{base_url}/v1/vectorize",
            body=b"x",
            headers={
                "content-type": "image/png",
                "content-length": str(33 * 1024 * 1024),
            },
        )
        assert oversized_status == 413
    finally:
        process.terminate()
        process.wait(timeout=10.0)
