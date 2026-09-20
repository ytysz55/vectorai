# Deterministic degradation tools

`generate_variants.py` expands a procedural dataset into T0–T3 raster variants. Every case records its derived seed, dimensions, Lanczos kernel, sRGB operation space, JPEG quality/subsampling, Gaussian blur radius, alpha quantization, background, noise level, Pillow version, and NumPy version.

The pipeline is deterministic under the pinned `uv.lock`. PNG/JPEG encoder version changes are therefore manifest-visible toolchain changes and require a benchmark dataset version bump.

```bash
uv run python tools/dataset/generate_fixtures.py
uv run python tools/degradation/generate_variants.py
```

Generated payloads live under `datasets/generated/` and are intentionally ignored by Git. Their manifest and hashes are the reproducibility boundary.
