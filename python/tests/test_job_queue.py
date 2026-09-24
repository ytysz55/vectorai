from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import cast

import pytest

from vectorai_api.jobs import (
    IdempotencyConflictError,
    IdempotencyStoreError,
    JobBusyError,
    JobManager,
)


def _wait_done(manager: JobManager, job_id: str) -> dict[str, object]:
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        status = manager.status(job_id)
        if status["state"] not in {"accepted", "running"}:
            return status
        time.sleep(0.03)
    raise AssertionError("queued job did not finish")


def test_bounded_fifo_queue_keyed_replay_conflict_and_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = JobManager(
        tmp_path,
        resvg_executable=None,
        resvg_command_prefix=None,
        max_job_seconds=10,
        max_queued_jobs=2,
    )
    deferred: list[threading.Thread] = []
    actual_start = threading.Thread.start

    def postpone(thread: threading.Thread) -> None:
        deferred.append(thread)

    monkeypatch.setattr(threading.Thread, "start", postpone)
    first = manager.submit(
        b"bad-a", input_name="input.png", mode="geometric", idempotency_key="alpha"
    )
    second = manager.submit(
        b"bad-b", input_name="input.png", mode="geometric", idempotency_key="beta"
    )
    third = manager.submit(
        b"bad-c", input_name="input.png", mode="geometric", idempotency_key="gamma"
    )
    assert len(deferred) == 1
    assert second["state"] == third["state"] == "accepted"
    assert (
        manager.submit(b"bad-a", input_name="input.png", mode="geometric", idempotency_key="alpha")[
            "job_id"
        ]
        == first["job_id"]
    )
    with pytest.raises(IdempotencyConflictError):
        manager.submit(
            b"different", input_name="input.png", mode="geometric", idempotency_key="alpha"
        )
    with pytest.raises(JobBusyError):
        manager.submit(b"bad-d", input_name="input.png", mode="geometric")
    assert manager.cancel(cast(str, second["job_id"]))["state"] == "canceled"
    fourth = manager.submit(b"bad-d", input_name="input.png", mode="geometric")
    assert fourth["state"] == "accepted"
    status_text = json.dumps(manager.status(cast(str, first["job_id"])))
    sidecar = (tmp_path / cast(str, first["job_id"]) / "idempotency.json").read_text(
        encoding="utf-8"
    )
    assert "alpha" not in status_text and "alpha" not in sidecar
    monkeypatch.undo()
    actual_start(deferred[0])
    finished = [_wait_done(manager, cast(str, job["job_id"])) for job in (first, third, fourth)]
    assert all(record["state"] == "failed" for record in finished)
    assert isinstance(finished[1]["started_at"], str)
    assert isinstance(finished[2]["started_at"], str)
    assert finished[1]["started_at"] <= finished[2]["started_at"]
    assert manager.active is None
    assert not manager.queued
    restarted = JobManager(
        tmp_path,
        resvg_executable=None,
        resvg_command_prefix=None,
        max_job_seconds=10,
        max_queued_jobs=2,
    )
    replay = restarted.submit(
        b"bad-a", input_name="input.png", mode="geometric", idempotency_key="alpha"
    )
    assert replay["job_id"] == first["job_id"]
    with pytest.raises(IdempotencyConflictError):
        restarted.submit(
            b"bad-a", input_name="input.jpg", mode="geometric", idempotency_key="alpha"
        )


def test_corrupt_persisted_key_index_fails_closed(tmp_path: Path) -> None:
    fixture_path = Path(__file__).resolve().parents[2] / "schemas/fixtures/valid/local-job.json"
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    job_root = tmp_path / payload["job_id"]
    job_root.mkdir()
    (job_root / "job-status.json").write_text(json.dumps(payload), encoding="utf-8")
    (job_root / "idempotency.json").write_text("{bad-json", encoding="utf-8")
    manager = JobManager(
        tmp_path,
        resvg_executable=None,
        resvg_command_prefix=None,
        max_job_seconds=10,
        max_queued_jobs=2,
    )
    assert manager.status(payload["job_id"])["state"] == "success"
    with pytest.raises(IdempotencyStoreError):
        manager.submit(b"bad", input_name="input.png", mode="geometric", idempotency_key="new-key")
