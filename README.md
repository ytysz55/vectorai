# VectorAI

Deterministic, topology-first raster-to-vector reconstruction for logos, icons, Turkish text outlines, and clean line art.

> We don't trace pixels. We reconstruct design intent.

## Status

**E0 foundation, E1 benchmark harness, E2 binary, E3 multicolor/demo, and E4 stroke/line-art are complete.** Gates G0–G3 have passed; the next implementation phase is **E5 — global optimization**. The implementation order is deliberately gated:

1. benchmark harness,
2. binary vertical slice,
3. mandatory multicolor reconstruction,
4. stroke reconstruction,
5. global optimization,
6. local-first web UI hardening.

The binding product requirements and task list live in [`docs/PRD_MOTOR_GELISTIRME_PLANI.md`](docs/PRD_MOTOR_GELISTIRME_PLANI.md).

## Supported development platforms

- Windows x86-64
- Linux x86-64

macOS is not an initial release target.

## Planned architecture

```text
React/TypeScript UI
        ↓ localhost
FastAPI service
        ↓ pybind11
C++17 vector reconstruction engine
```

The engine remains native and offline-capable. It does not run in browser/WASM in the initial product.

## Bootstrap requirements

- CMake 3.24+
- Ninja
- A C++17 compiler: MSVC 2022, GCC 12+, or Clang 16+
- Python 3.12+
- uv

## Build the native engine

```bash
cmake --preset dev-debug
cmake --build --preset dev-debug
ctest --preset dev-debug
```

## Run Python checks

```bash
uv sync --all-extras --dev
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

## Run the E2 binary CLI

The Python entry point performs safe PNG/JPEG decode, sRGB/alpha normalization, reliability analysis, native topology-first reconstruction, renderer validation, and writes an atomic artifact bundle containing SVG, preview, metrics, manifests, and validation results.

```bash
uv run python -m vectorai_cli vectorize input.png \
  --output-dir out/vectorized \
  --native-executable out/build/dev-debug/vectorai_binary_cli \
  --resvg-executable /path/to/resvg
```

Use the `.exe` suffix on Windows.

## Run the E1 benchmark smoke

The smoke test uses one deterministic seed, pinned resvg, VTracer, and GPL-isolated Potrace. Tool paths must point to binaries matching `benchmark/configs/*.lock.json`.

```bash
uv run python tools/benchmark/run_smoke.py \
  --vtracer /path/to/vtracer \
  --potrace /path/to/potrace \
  --resvg /path/to/resvg \
  --verify-repeat
```

## Run Gate G1

```bash
uv run python tools/benchmark/run_e2_gate.py \
  --native out/build/dev-debug/vectorai_binary_cli \
  --vtracer /path/to/vtracer \
  --potrace /path/to/potrace \
  --resvg /path/to/resvg \
  --output benchmark/reports/e2-g1
```

The current 20-case procedural binary gate records 100% exact topology, zero hard failures, and a 73.21% node advantage over VTracer while remaining in an equal-or-better fidelity band.

## Run Gate G3

The stroke gate exercises fill/stroke routing, topology-preserving centerlines, width models, caps/joins, T/X junctions, cut outlines, and fill-vs-stroke Pareto selection.

```bash
uv run python tools/benchmark/run_stroke_g3.py \
  --resvg /path/to/resvg \
  --output out/stroke-g3 \
  --verify-repeat
```

The locked 13-case G3 corpus records 92.31% routing accuracy, exact connectivity and junction valence, 0.5 px centerline p95, 0.337 px mean width error, 100% style/cut validation, and 54.95% node advantage over fill. The local web demo exposes this branch as **Stroke / line-art** and provides both editable stroke SVG and closed cut-outline SVG.

## Current dependency policy

The E0 native core is intentionally dependency-free. OpenCV, Eigen, Ceres, Clipper2, and pybind11 are introduced only when their owning tasks begin. Ceres must be built without SuiteSparse unless a commercial license decision explicitly changes that policy.
