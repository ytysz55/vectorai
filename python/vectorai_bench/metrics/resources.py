"""Cross-platform wall-time, CPU-time, and peak-RSS measurements."""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass

import psutil  # type: ignore[import-untyped]

METRIC_VERSION = "1.0.0"


@dataclass(frozen=True, slots=True)
class ResourceMetrics:
    metric_version: str
    wall_time_ms: float
    cpu_time_ms: float
    peak_rss_bytes: int


@dataclass(frozen=True, slots=True)
class MeasuredResult[T]:
    value: T
    resources: ResourceMetrics


def measure_callable[T](
    operation: Callable[[], T], *, sample_interval_seconds: float = 0.002
) -> MeasuredResult[T]:
    if sample_interval_seconds <= 0.0:
        raise ValueError("sample interval must be positive")
    process = psutil.Process(os.getpid())
    peak_rss = process.memory_info().rss
    stop = threading.Event()

    def sample() -> None:
        nonlocal peak_rss
        while not stop.wait(sample_interval_seconds):
            try:
                peak_rss = max(peak_rss, process.memory_info().rss)
            except psutil.Error:
                return

    sampler = threading.Thread(target=sample, name="vectorai-rss-sampler", daemon=True)
    wall_start = time.perf_counter()
    cpu_start = time.process_time()
    sampler.start()
    try:
        value = operation()
    finally:
        stop.set()
        sampler.join()
        with suppress(psutil.Error):
            peak_rss = max(peak_rss, process.memory_info().rss)
    resources = ResourceMetrics(
        metric_version=METRIC_VERSION,
        wall_time_ms=(time.perf_counter() - wall_start) * 1000.0,
        cpu_time_ms=(time.process_time() - cpu_start) * 1000.0,
        peak_rss_bytes=peak_rss,
    )
    return MeasuredResult(value=value, resources=resources)
