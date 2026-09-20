# Local-first web UI

A React/Vite review surface for the E3 investment demo. It uploads raster bytes only to the loopback FastAPI service, displays the source against the rendered SVG preview, and exposes the local proof-artifact bundle.

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
```

Build output is written to `apps/web/dist/` and is ignored by Git.
