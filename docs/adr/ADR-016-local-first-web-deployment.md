# ADR-016: Local-first web deployment and localhost security

- **Status:** Accepted for the E3 investment demo
- **Scope:** FastAPI localhost service, React/Vite review UI, local artifact storage, and optional future desktop packaging
- **Review trigger:** API-001/API-002 production job work, remote access requirements, automatic retention, authentication, or a Tauri packaging decision

## Context

The investment demo needs a browser-based upload and review experience without sending customer source images to a hosted service. A browser UI still requires an HTTP boundary for the native/local engine and artifact downloads. Binding that service broadly, accepting arbitrary origins, or exposing arbitrary filesystem paths would contradict the local-first privacy claim.

The E3 demo is synchronous and single-machine. It is not yet the production job API described by API-001/API-002: there is no queue, cancellation, idempotency key, authentication, multi-user isolation, or automatic retention policy.

## Decision

### Network boundary

- The API starter binds only to `127.0.0.1` or `::1`; no LAN/public bind option is exposed.
- The combined demo launcher uses fixed loopback endpoints: API `127.0.0.1:8000` and Vite UI `127.0.0.1:5173`.
- The engine and renderer execute as local processes. Source bytes are never forwarded to a remote inference or storage service.
- API documentation endpoints and the OpenAPI endpoint are disabled in the demo process.

### Browser origin policy

- CORS is restricted to `http://127.0.0.1:5173` and `http://[::1]:5173`.
- Allowed methods are `GET` and `POST`.
- Allowed request headers are limited to content type, local filename, and mode selection.
- Credentials are disabled. The E3 service has no cookie or bearer-token authentication because it is not permitted to bind outside loopback.

### Upload and execution limits

- Uploads accept only raw PNG or JPEG request bodies.
- The maximum request size is 32 MiB and is checked from both `Content-Length` and the received body.
- Decode and pixel-count limits remain owned by the engine and are enforced after upload.
- Filenames are reduced to a known `input.png` or `input.jpg`; caller-provided directories are discarded.
- The reference renderer must be an explicitly configured local executable or command prefix.

### Job and artifact confinement

- Every run is stored below one configured local jobs directory.
- Job IDs combine the source SHA-256 prefix with an opaque random suffix; they are validated before path construction.
- Resolved job paths must remain descendants of the jobs root.
- Artifact retrieval is allowlisted to `output.svg`, `preview.png`, `scene.json`, and `run-manifest.json`.
- Arbitrary path traversal and arbitrary local-file serving are rejected.

### Retention and privacy

- E3 jobs persist locally until the user manually removes the configured jobs directory.
- No automatic upload, telemetry, cloud backup, or background synchronization is performed by the application.
- Automatic expiry, secure deletion, user-visible cleanup, and path-free structured logs are deferred to ADR-014 and OBS-003 before pilot release.
- The current persistence behavior must be stated in demo documentation; it is not a production retention promise.

### Desktop packaging

- No separate desktop UI codebase will be created for E3.
- If offline installation demand is validated, the same React UI and localhost API may be wrapped with Tauri after dependency, updater, signing, and localhost lifecycle review.
- Browser/WASM engine execution is outside the initial scope.

## Alternatives considered

### Hosted API

Rejected for the investment demo because it weakens the privacy claim, adds authentication and storage obligations, and is unnecessary for local deterministic execution.

### Bind to `0.0.0.0` for convenience

Rejected. LAN exposure without authentication would allow other local-network clients to submit images or retrieve artifacts.

### Browser-only/WASM engine

Deferred. The native C++/Python pipeline and reference-renderer subprocesses are not currently packaged for browser execution.

### Separate desktop application

Rejected for E3 because it duplicates the UI and deployment surface before desktop demand is proven.

## Consequences

- The demo works only on the machine running the API and UI.
- Fixed loopback origins simplify the security model but prevent arbitrary development ports without a reviewed CORS/config change.
- Local jobs consume disk until manually removed.
- Production queueing, cancellation, authentication, cleanup, and multi-user guarantees remain open work and must not be inferred from the E3 demo.

## Validation evidence

- `python/tests/test_local_api.py` starts the real loopback server, uploads a raster, retrieves allowlisted artifacts, verifies CORS, rejects oversized input, and checks traversal confinement.
- `tools/demo/serve_local_api.py` limits host choices to loopback addresses.
- `tools/demo/serve_local_demo.py` starts the API and Vite UI on fixed loopback endpoints.
- `apps/api/README.md` and `apps/web/README.md` document local startup and the local-only boundary.
