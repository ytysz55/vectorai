# ADR-008: Determinism contract

- **Status:** Accepted for E0
- **Scope:** Windows x86-64 and Linux x86-64
- **Review trigger:** SP-08 cross-platform determinism spike or a dependency that changes floating-point behavior

## Context

The engine must support trustworthy benchmark comparisons and repeatable customer outputs. Raw run artifacts also contain observations such as runtime and peak memory that are intentionally variable. Treating every output byte as deterministic would make the contract impossible; treating determinism as best effort would make regressions hard to distinguish from noise.

## Decision

### Same-platform contract

For the same:

- input bytes,
- engine build ID,
- dependency versions,
- mode profile and config hashes,
- seed,
- thread count and determinism policy,
- operating-system family and CPU architecture,

the engine must produce byte-identical **canonical artifacts**:

- SVG,
- topology/scene artifact,
- validation decisions,
- semantic metric values,
- the reproducibility projection of the run manifest.

The following **observational fields** are excluded from the determinism digest:

- wall-clock timestamps,
- stage and total durations,
- peak RSS,
- host name and process ID,
- absolute filesystem paths.

### Cross-platform contract

Windows and Linux must produce:

- identical topology and discrete candidate choices,
- equivalent canonical path structure,
- geometry and raster results within versioned tolerances.

Byte-identical Windows/Linux floating-point output is not a P0 promise. SP-08 may strengthen this contract after measuring compiler and standard-library differences.

### Implementation rules

1. Every externally visible entity receives a stable ID derived from canonical traversal, never an address or insertion accident.
2. All decision-making collections have an explicit stable sort and tie-break key.
3. Iteration order of unordered containers must not influence output.
4. Every randomized operation receives the run seed or a deterministically derived child seed.
5. Parallel reductions use a fixed reduction tree or are serialized in strict mode.
6. `-ffast-math` and equivalent unsafe floating-point modes are forbidden in strict builds.
7. Non-finite values are errors; they are never serialized.
8. Locale-dependent parsing or formatting is forbidden.
9. JSON determinism projection uses UTF-8, LF, sorted object keys, finite JSON numbers, and no insignificant whitespace.
10. SVG uses the canonical geometry and numeric rules from ADR-011.
11. Dependency, compiler, profile, serializer, metric, and schema versions are recorded in the manifest.
12. Strict mode starts with one engine worker thread. Parallel execution may be enabled only after its deterministic schedule is tested.

## Manifest digest

The run manifest is split conceptually into:

- **identity/reproducibility fields**, included in the semantic digest;
- **observations**, retained for performance analysis but excluded from the digest.

The schema may store both in one JSON document. The digest implementation must use an explicit allowlist projection rather than deleting a denylist of variable fields.

## Alternatives considered

### Byte-identical output across every platform

Rejected for P0 because libm, compiler optimization, and renderer differences must first be measured. It remains a possible later strengthening.

### Best-effort determinism

Rejected because it cannot support locked benchmark gates or reliable regression analysis.

### Disable every form of parallelism permanently

Rejected as a long-term rule. Strict mode begins single-threaded, while deterministic parallel scheduling remains allowed after proof.

## Consequences

- Some optimizations require deterministic implementations before release.
- Performance telemetry cannot be part of a byte-level reproducibility assertion.
- CI must execute representative jobs twice and compare canonical digests.
- Cross-platform tests initially use discrete equality plus numeric/render tolerances.

## Validation evidence required

- Same-platform double-run golden test.
- Stable ordering property tests.
- Seed derivation tests.
- Windows/Linux comparison report from SP-08.
