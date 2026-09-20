# SPIKE-007 — Subpixel boundary evidence

**Decision:** Continue with the antialias-profile estimator for E2.

## Calibration

A vertical foreground/background boundary is placed analytically at `x = 2.25`. Pixel centers on the two sides carry foreground evidence `1.0` and `1/3`. Linear threshold crossing at `0.5` recovers an offset of `+0.25` from the grid edge.

| Estimator | Estimated x | Absolute error |
| --- | ---: | ---: |
| Pixel edge | 2.00 | 0.25 px |
| Subpixel profile | 2.25 | < 1e-6 px |

The native unit test also verifies the no-subpixel ablation, reliability-dependent covariance, finite residual/support fields, and junction exclusion on diagonal-touch masks.

## Production constraints

- Offset is clamped to `[-0.5, 0.5]` pixel.
- Low-contrast profiles fall back to the pixel edge rather than extrapolating.
- Every canonical half-edge pair produces one shared evidence sample.
- Vertices with non-manifold/diagonal-touch degree are marked excluded for local fitting.
- Reliability affects covariance, not topology.

This spike proves the estimator’s direction on controlled profiles; it does not claim a full PSF model. Blur-kernel inference remains a later refinement.
