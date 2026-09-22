"""Shared helpers for hermetic external-tool test doubles."""

from __future__ import annotations

import os
import sys
from pathlib import Path

RGBA_PNG_WRITER_SOURCE = r"""
import struct
import zlib
from pathlib import Path


def write_rgba_pixels(path, width, height, pixels):
    stride = width * 4
    raw = b''.join(
        b'\x00' + bytes(pixels[offset:offset + stride])
        for offset in range(0, height * stride, stride)
    )

    def chunk(kind, payload):
        checksum = zlib.crc32(kind + payload) & 0xffffffff
        return (
            struct.pack('>I', len(payload))
            + kind
            + payload
            + struct.pack('>I', checksum)
        )

    header = struct.pack('>IIBBBBB', width, height, 8, 6, 0, 0, 0)
    Path(path).write_bytes(
        b'\x89PNG\r\n\x1a\n'
        + chunk(b'IHDR', header)
        + chunk(b'IDAT', zlib.compress(raw))
        + chunk(b'IEND', b'')
    )


def write_rgba_png(path, width, height, color):
    write_rgba_pixels(path, width, height, bytes(color) * width * height)
""".strip()


def active_python_executable() -> str:
    """Return the active environment launcher without resolving POSIX venv symlinks."""
    environment = Path(os.environ.get("VIRTUAL_ENV", sys.prefix))
    relative = Path("Scripts/python.exe") if os.name == "nt" else Path("bin/python")
    candidate = environment / relative
    if not candidate.is_file():
        raise RuntimeError(f"active Python executable does not exist: {candidate}")
    return str(candidate)
