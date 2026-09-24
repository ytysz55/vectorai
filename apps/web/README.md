# Local-first web UI

A React/Vite review surface for E7 local jobs. It uploads raster bytes only to the loopback FastAPI service, polls typed job states, supports cancellation, displays the source against a **validated** vector preview, and exposes only published local proof artifacts. No remote fonts or inference calls are made.

## Run

Install the pinned web dependencies once:

```bash
cd apps/web
npm ci
```

Then start both loopback processes with one command from the repository root:

```bash
uv run python tools/demo/serve_local_demo.py --resvg /path/to/resvg
```

Vite binds to `127.0.0.1:5173`; the UI calls the API at `127.0.0.1:8000`. API CORS is restricted to the two loopback Vite origins, so no LAN or remote origin can submit source images.

```bash
npm run build
npm test
```

The four controls map to distinct job modes: **faithful** and **minimal** use pinned E5 optimizer profiles, **geometric** uses the fast topology-checked baseline, and **stroke** uses the line-art pipeline. `success`, `degraded`, and `needs_review` can publish artifacts; `failed`, `unsupported`, and `canceled` cannot. Canceled or interrupted jobs require a new submission. A transient lost upload response reuses the same idempotency key for the same selected file/mode; after a known job reaches a terminal state a new click gets a new key. The legacy synchronous `/v1/vectorize` endpoint is not used.

Build output is written to `apps/web/dist/` and is ignored by Git. Page reload currently loses the UI's active job ID, but the local API status and artifacts persist; cross-session UI restoration is future scope.
