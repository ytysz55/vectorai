# Benchmark configurations

Versioned benchmark suites, metric profiles, renderer locks, and baseline presets live here.

- `metric-suite-v1.json`: topology-first metric definitions and normalization.
- `optimizer-profiles-v1.json`: E5 objective weights, deterministic bounds, and render-rank policy for all four modes.
- `resvg.lock.json`: pinned Windows/Linux reference-renderer archives and executables.
- `vtracer.lock.json`: pinned VTracer 0.6.4 artifacts and three presets.
- `potrace.lock.json`: GPL-isolated Potrace 1.16 source/Windows artifact and binary presets.

Archive and executable SHA-256 values are release inputs. Updating any lock requires a benchmark dataset/report version review.

## Optimizer objective normalization v1

Topology is a hard eligibility gate and never receives a weighted penalty. Eligible candidates use five finite `[0, 1]` terms:

| Term | Raw unit | v1 normalization | Scale behavior |
| --- | --- | --- | --- |
| fidelity | premultiplied linear-RGBA RMSE | identity | resolution independent |
| boundary | RMS pixels | divide by image diagonal, clamp | invariant when image and residual scale together |
| complexity | node count | `ratio / (1 + ratio)` against the pre-opt baseline | invariant when candidate and baseline counts scale together |
| regularization | RMS pixels | divide by image diagonal, clamp | invariant when image and residual scale together |
| color | normalized channel RMS | identity | resolution independent |

Profile weights sum to one. Runtime and RSS are observations and are not objective terms or semantic-hash inputs.
