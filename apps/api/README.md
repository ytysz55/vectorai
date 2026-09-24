# Local API

The service is **loopback-only**. It runs the engine and renderer locally, never forwards source pixels to a remote service, and only serves allowlisted artifacts from the configured jobs directory. CORS permits the fixed local Vite origins.

## Start

For the combined investment demo, see [`../web/README.md`](../web/README.md). To run just the API:

```bash
uv sync --all-extras --dev
uv run python tools/demo/serve_local_api.py \
  --resvg /path/to/resvg --jobs-dir out/local-api-jobs
```

`--host` accepts only `127.0.0.1` or `::1` (default `127.0.0.1:8000`). The reference renderer must be explicitly configured. Only a **single API process** may own a jobs directory; multi-process admission is not yet supported.

## E7 job endpoints (API-001/002)

- `POST /v1/jobs` — raw PNG/JPEG upload, `202` with a [versioned job status](../../schemas/local-job.schema.json). Optional `X-VectorAI-Filename` selects only `input.png` or `input.jpg`; `X-VectorAI-Mode` accepts **`geometric` or `stroke`**. The other demo labels are not presented as working optimization modes here. Maximum request body: 32 MiB, enforced while streaming. Optional `Idempotency-Key` (visible ASCII, 1–128 bytes) replays the original job for the same input/mode/normalized extension, even if it has completed; reuse with different data returns typed `409 IDEMPOTENCY_CONFLICT`.
- `GET /v1/jobs/{job_id}` — durable `accepted`, `running`, `success`, `degraded`, `needs_review`, `failed`, or `canceled` state, with typed `error` on failure. `unsupported` is reserved for future typed intake routing. Status includes an input SHA-256 for **local** audit; do not publish the record remotely without permission.
- `POST /v1/jobs/{job_id}/cancel` — accepted work becomes canceled before starting. Running work sets `cancel_requested`, kills the worker **and its renderer descendants**, and becomes canceled only after the process stops. A completed job returns `409` (`JOB_ALREADY_TERMINAL`). Cancellation does not delete a previously completed artifact bundle.
- `GET /v1/jobs/{job_id}/artifacts/{artifact_name}` — allowlisted artifacts are served only after a validated `success`, `degraded`, or `needs_review` result. In-progress/failed/canceled jobs do not publish files. No arbitrary paths or symlink artifacts are served.
- `GET /health` — readiness and `local_only: true`.

The legacy synchronous `POST /v1/vectorize` stays available for the E3 demo; it is **not** the E7 job API. Its `faithful`/`minimal` labels currently use the default geometric pipeline and must not be represented as distinct optimized modes. UI-001 will wire real profiles and migrate to job polling before claiming all four UI modes.

**Admission and errors:** One worker runs while up to **two jobs wait in FIFO order** by default. `--max-queued-jobs` configures 0–16; a full queue returns typed retryable `429 RESOURCE_LIMIT` for new work, but an existing key may still be replayed. `--max-parallel-uploads` configures 1–16 concurrent bounded upload buffers (default 3); excess uploads also return typed `429`. Malformed/oversized uploads return typed errors. `--job-timeout-seconds` defaults to 180 (allowed `(0, 3600]`). Completion/timeout/cancel races resolve to one terminal state. There is **no OS-level RAM sandbox**; the upload/decode/pixel budgets and worker deadline do not bound total RSS.

**Storage and recovery:** Source bytes, private worker configuration, local status, validated artifacts, and a **SHA-256-only** private key index stay under `--jobs-dir`; the raw idempotency key is not stored. Status writes are atomic. On restart, unfinished/queued jobs become `failed/JOB_INTERRUPTED` and are not automatically resumed; a repeated key returns that same failed job, so a retry requires a new key. Corrupt keyed history disables keyed admission (`503 IDEMPOTENCY_STORE_UNAVAILABLE`). Finished results remain readable. Abrupt termination of the API process can leave an orphan renderer; restart does not assert that it can identify or kill a PID safely. Normal shutdown and explicit cancellation stop owned workers. Jobs persist until the user removes the jobs directory; automatic retention, secure deletion and multi-process ownership are not yet promised.
