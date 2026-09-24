from __future__ import annotations

import hashlib
import json
import threading
import time
from pathlib import Path
from typing import Any, cast

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

from vectorai_api.jobs import JobManager

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = json.loads((ROOT / "schemas/local-job.schema.json").read_text(encoding="utf-8"))


def _manager(root: Path, seconds: float = 5.0) -> JobManager:
    return JobManager(
        root,
        resvg_executable=None,
        resvg_command_prefix=None,
        max_job_seconds=seconds,
    )


def test_cancel_accepted_job_never_starts_worker(tmp_path: Path, monkeypatch: Any) -> None:
    manager = _manager(tmp_path)
    deferred: list[threading.Thread] = []
    actual_start = threading.Thread.start

    def postpone(thread: threading.Thread) -> None:
        deferred.append(thread)

    monkeypatch.setattr(threading.Thread, "start", postpone)
    try:
        accepted = manager.submit(b"not an image", input_name="input.png", mode="geometric")
        job_id = cast(str, accepted["job_id"])
        canceled = manager.cancel(job_id)
        assert canceled["state"] == "canceled"
        assert not (tmp_path / job_id / "worker-result.json").exists()
        cast(Any, Draft202012Validator(SCHEMA)).validate(canceled)
        assert manager.status(job_id)["state"] == "canceled"
    finally:
        monkeypatch.undo()
        for thread in deferred:
            actual_start(thread)
            thread.join(timeout=5)
        manager.shutdown()


def test_restart_marks_interrupted_job_failed_without_exposing_artifacts(tmp_path: Path) -> None:
    source_hash = hashlib.sha256(b"image").hexdigest()
    job_id = f"{source_hash}-123456789abc"
    job_root = tmp_path / job_id
    job_root.mkdir()
    existing = json.loads(
        (ROOT / "schemas/fixtures/valid/local-job.json").read_text(encoding="utf-8")
    )
    existing.update(
        {
            "job_id": job_id,
            "state": "running",
            "input_sha256": source_hash,
            "artifacts": {},
            "completed_at": None,
        }
    )
    (job_root / "job-status.json").write_text(json.dumps(existing), encoding="utf-8")
    manager = _manager(tmp_path)
    recovered = manager.status(job_id)
    assert recovered["state"] == "failed"
    assert isinstance(recovered["error"], dict)
    assert recovered["error"]["code"] == "JOB_INTERRUPTED"
    assert not manager.can_download(job_id)
    cast(Any, Draft202012Validator(SCHEMA)).validate(recovered)


def test_worker_deadline_kills_process_and_reports_resource_limit(tmp_path: Path) -> None:
    manager = _manager(tmp_path, seconds=0.001)
    accepted = manager.submit(b"not an image", input_name="input.png", mode="geometric")
    job_id = cast(str, accepted["job_id"])
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        record = manager.status(job_id)
        if record["state"] == "failed":
            assert isinstance(record["error"], dict)
            assert record["error"]["code"] == "RESOURCE_LIMIT"
            cast(Any, Draft202012Validator(SCHEMA)).validate(record)
            break
        time.sleep(0.02)
    else:
        manager.shutdown()
        raise AssertionError("worker deadline did not produce terminal status")
