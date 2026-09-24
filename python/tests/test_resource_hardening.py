from __future__ import annotations

import asyncio
import io
import sys
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, cast

import pytest
from PIL import Image

from vectorai_api.app import read_bounded_body
from vectorai_bench.external_tools import ToolStatus, run_command
from vectorai_engine.decode import DecodeLimits, decode_bytes, decode_path
from vectorai_engine.errors import EngineFailure, ErrorCode


def _png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGBA", (64, 64), (255, 0, 0, 255)).save(buffer, format="PNG")
    return buffer.getvalue()


def test_decode_limits_reject_small_compressed_large_decoded_input(tmp_path: Path) -> None:
    payload = _png()
    with pytest.raises(EngineFailure) as pixels:
        decode_bytes(payload, limits=DecodeLimits(max_pixels=1024))
    assert pixels.value.error.code is ErrorCode.RESOURCE_LIMIT
    with pytest.raises(EngineFailure) as memory:
        decode_bytes(payload, limits=DecodeLimits(max_decoded_bytes=4096))
    assert memory.value.error.code is ErrorCode.RESOURCE_LIMIT
    source = tmp_path / "image.png"
    source.write_bytes(payload)
    with pytest.raises(EngineFailure) as compressed:
        decode_path(source, limits=DecodeLimits(max_input_bytes=len(payload) - 1))
    assert compressed.value.error.code is ErrorCode.RESOURCE_LIMIT


def test_subprocess_timeout_and_environment_isolation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VECTORAI_SECRET_MARKER", "sensitive-user-data")
    script = tmp_path / "tool.py"
    script.write_text(
        "import os, sys, time\n"
        "if sys.argv[-1] == 'wait': time.sleep(5)\n"
        "print(os.environ.get('VECTORAI_SECRET_MARKER', 'redacted'))\n",
        encoding="utf-8",
    )
    timed_out = run_command((sys.executable, str(script), "wait"), timeout_seconds=0.05)
    assert timed_out.status is ToolStatus.TIMEOUT
    isolated = run_command((sys.executable, str(script), "now"), timeout_seconds=5.0)
    assert isolated.status is ToolStatus.SUCCESS
    assert isolated.stdout.strip() == "redacted"


def test_chunked_api_upload_rejects_body_before_allocating_job() -> None:
    class ChunkedRequest:
        async def stream(self) -> AsyncIterator[bytes]:
            yield b"a" * 64
            yield b"b" * 64

    with pytest.raises(Exception) as too_large:
        asyncio.run(read_bounded_body(cast(Any, ChunkedRequest()), 100))
    assert getattr(too_large.value, "status_code", None) == 413
    assert asyncio.run(read_bounded_body(cast(Any, ChunkedRequest()), 128)) == (
        b"a" * 64 + b"b" * 64
    )
