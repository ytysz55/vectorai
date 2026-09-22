"""Shared helpers for hermetic external-tool test doubles."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def active_python_executable() -> str:
    """Return the active environment launcher without resolving POSIX venv symlinks."""
    environment = Path(os.environ.get("VIRTUAL_ENV", sys.prefix))
    relative = Path("Scripts/python.exe") if os.name == "nt" else Path("bin/python")
    candidate = environment / relative
    if not candidate.is_file():
        raise RuntimeError(f"active Python executable does not exist: {candidate}")
    return str(candidate)
