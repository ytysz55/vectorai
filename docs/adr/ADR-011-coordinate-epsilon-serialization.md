# ADR-011: Coordinate, epsilon, and serialization policy

- **Status:** Accepted for E0 with provisional numeric thresholds
- **Scope:** Native geometry, metrics, optimizer conditioning, and SVG export
- **Review trigger:** SP-03 seam matrix, SP-08 determinism results, or a failed geometry robustness gate

## Context

Raster pixels, subpixel evidence, topology operations, continuous optimization, metrics, and SVG serialization must agree on coordinates and tolerances. A single unnamed global epsilon would mix numerical noise with product-level geometry tolerances and could silently change topology.

## Decision

### Coordinate system

- Native geometry uses IEEE-754 `double`.
- Raster sample/color buffers may use `float`, but fitting and topology coordinates use `double`.
- The image domain is `[0, width] × [0, height]`.
- The top-left image corner is `(0, 0)`.
- Pixel `(x, y)` has center `(x + 0.5, y + 0.5)`.
- Positive Y points downward, matching the default SVG viewport.
- Default SVG output uses `viewBox="0 0 width height"`.
- Distance metrics report both pixels and a value normalized by image diagonal.
- Optimizer parameter blocks may use diagonal-normalized coordinates internally, but public artifacts remain in pixel coordinates.

### Named tolerance classes

No algorithm may depend on a generic `EPSILON` constant. Tolerances are named and versioned by purpose:

1. **Arithmetic epsilon:** Detects floating-point degeneracy. Initial value is `64 × machine_epsilon × max(width, height, 1)`.
2. **Topology snap tolerance:** Controls whether independently estimated points may represent the same topological vertex. Initial value is `min(1e-3, max(1e-7, 1e-6 × max(width, height)))` pixels.
3. **Validation tolerance:** Product/profile-specific geometric allowance; never reused as arithmetic epsilon.
4. **Metric sampling tolerance:** Owned and versioned by each metric implementation.
5. **Export quantization:** Initial coordinate quantum is `1e-4` pixels.

Topology snap may only merge entities if graph invariants and local label evidence remain valid. Distance alone is insufficient.

The provisional thresholds must be benchmarked before G1. Changing them requires a profile/serializer version bump and a regression report.

### Canonical geometry and path rules

- Foreground outer cycles are clockwise in the Y-down SVG coordinate system.
- Hole cycles are counter-clockwise.
- A cycle begins at the lexicographically smallest quantized `(x, y)` vertex; ties use outgoing canonical geometry ID.
- Regions, cycles, and paths are serialized by stable ID.
- Shared geometry is quantized and formatted once. Its twin consumes the exact same values in reverse order.
- Primitive reversal must preserve the same locus and swap only orientation-dependent parameters.
- Zero-length segments after quantization are rejected before export.

### Numeric serialization

- Decimal separator is `.` and formatting is locale independent.
- Negative zero is serialized as `0`.
- Non-finite numbers are forbidden.
- Trailing zeros and a trailing decimal point are removed.
- Scientific notation is not used for ordinary image-coordinate ranges.
- The serializer version is written to the run manifest.

## Alternatives considered

### Normalized `[0, 1]` coordinates everywhere

Rejected because raster evidence and SVG inspection are clearer in pixel coordinates. Normalization is still allowed inside optimizers.

### Integer/fixed-point geometry everywhere

Deferred. It may simplify exact topology but complicates subpixel fitting and continuous optimization. Exact predicates may be added selectively.

### One global epsilon

Rejected because arithmetic safety, topology, validation, and user-facing tolerance are different concepts.

### Independent serialization of twin boundaries

Rejected because different rounding paths can create seams and violate the shared-boundary contract.

## Consequences

- Algorithms must declare which tolerance class they consume.
- Topology operations require evidence-aware merging rather than raw proximity.
- Golden SVG output becomes stable and reviewable.
- Export precision may be changed only through a versioned decision and benchmark evidence.

## Validation evidence required

- Translation and scale property tests.
- Shared-edge forward/reverse serialization golden tests.
- Export → parse → export idempotence.
- SP-03 renderer seam matrix.
- Degenerate and negative-zero fixtures.
