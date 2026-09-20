# Local API

The E3 service is a **loopback-only** FastAPI process. It accepts source bytes locally, invokes the deterministic multicolor engine locally, and serves the resulting local artifact bundle. It makes no outbound requests. CORS is limited to the Vite loopback origins `http://127.0.0.1:5173` and `http://[::1]:5173`.

## Start

For the complete investment demo (API plus web review UI), use the single launcher documented in [`../web/README.md`](../web/README.md).

To run just the API:

```bash
uv sync --all-extras --dev
uv run python tools/demo/serve_local_api.py \
  --resvg /path/to/resvg \
  --jobs-dir out/local-api-jobs
```

The API-only starter accepts only `127.0.0.1` or `::1` as `--host`; its default is `127.0.0.1:8000`.

## Endpoints

- `GET /health` — readiness and `local_only: true`.
- `POST /v1/vectorize` — raw `image/png` or `image/jpeg` request body. Optional `X-VectorAI-Filename` must end in `.png`, `.jpg`, or `.jpeg`.
- `GET /v1/jobs/{job_id}/artifacts/{artifact_name}` — only the known SVG, PNG and JSON artifacts for a completed local job.

`POST /v1/vectorize` has a 32 MiB request limit. Jobs use an opaque SHA-256-prefixed ID and artifact lookup is confined to the configured jobs directory.
