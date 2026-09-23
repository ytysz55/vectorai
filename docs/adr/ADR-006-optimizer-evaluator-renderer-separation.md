# ADR-006: Optimizer evaluator and reference renderer separation

- **Status:** Accepted for E5
- **Scope:** Global continuous optimization, hard topology validation, candidate evaluation, and final render-and-rank
- **Review trigger:** Gate G4 decision, a production Ceres migration, or a canonical renderer change

## Context

The E5 optimizer must improve geometry, color, width, and editability after scene topology has been fixed. Calling the pinned reference renderer inside every solver iteration would make optimization slow, operationally fragile, and difficult to differentiate. Using only an analytic approximation for the final decision would miss rasterizer behavior, alpha compositing, and scale-dependent artifacts.

The current multicolor and stroke scene models are implemented in Python, while the native C++ binary covers the E2 binary slice. There is no native representation of the E3/E4 scene, no binding layer, and no dependency in `vcpkg.json`. Adding Ceres before proving measurable optimization value would combine solver work with scene duplication, ABI design, dependency auditing, and cross-platform determinism risk.

## Decision

### Two evaluation tiers

E5 uses two deliberately separate tiers:

1. A deterministic in-process evaluator drives bounded refinement. It evaluates normalized geometric, color, width, smoothness, and complexity terms without launching an external renderer.
2. Pinned resvg is the final oracle for a bounded Top-K set. It renders accepted candidates at `0.5x`, `1x`, `2x`, and `4x` over transparent, black, white, and checkerboard backgrounds.

resvg is never called from an optimizer iteration. The final rank record contains all candidate scores and a stable winner identifier.

### Hard topology eligibility

Topology and structural invariants are eligibility checks, not weighted objective terms. A candidate is rejected before scoring if it changes any required invariant, including:

- component or hole counts;
- connectivity, adjacency, or junction valence;
- face/edge incidence or cycle ordering;
- shared canonical geometry or twin orientation;
- cycle closure;
- primitive kind or path structure;
- positive radius or width constraints.

A large numerical penalty may not substitute for a hard rejection. Shared boundaries expose one canonical parameter block; twin faces may not optimize duplicate coordinates independently.

### Solver-independent contracts first

E5 first introduces immutable parameter-block, objective, validation, and result contracts with a deterministic bounded Python/NumPy backend. The backend uses stable parameter ordering, a fixed step schedule, fixed evaluation/iteration limits, deterministic tie-breaks, and no wall-clock-based semantic decision.

This prototype is named `OPT-003P`. It does not claim to complete a Ceres integration. `OPT-003C` is a conditional production migration after Gate G4 if optimization demonstrates measurable quality value or the Python backend misses the heavy-path runtime target. A Ceres backend must preserve the same parameter/result contract and use `WITH_SUITESPARSE=OFF` unless a later dependency review changes that decision.

### Determinism and fallback

The semantic digest includes profile/config hashes, canonical candidate order, normalized terms, hard-validation results, selected candidate, convergence reason, and fallback reason. Runtime and RSS remain observational and are excluded.

A divergent or non-finite optimization may return the pre-optimization scene as `degraded` only after that scene independently passes every hard validation. An invalid baseline fails; it is never used as a fallback.

## Alternatives considered

### Call resvg for every iteration

Rejected. Process startup and rasterization dominate the inner loop, and renderer availability would become a solver correctness dependency.

### Use only the internal evaluator

Rejected. Final raster quality, alpha behavior, and scale/background sensitivity must be decided by the pinned renderer.

### Add Ceres immediately

Deferred until Gate G4. The current scene ownership boundary would require premature C++ model duplication or a new binding layer before optimizer value is established.

### Encode topology as a large objective penalty

Rejected. Weight tuning could trade topology correctness for fidelity, violating the topology-first product contract.

## Consequences

- Inner-loop optimization remains deterministic, bounded, and testable without external processes.
- Final selection reflects actual canonical renderer behavior.
- Topology preservation is explicit and cannot be outweighed by fidelity.
- Python prototype performance is acceptable only for the E5 heavy/offline path until G4 measures it.
- The PRD distinguishes delivered solver-independent work from conditional Ceres migration.

## Validation evidence required

- Unit and scale-analysis tests for every normalized objective term.
- Four external, versioned, canonical-hashable mode profiles.
- Parameter-bound and hard-invariant tests for vertex, primitive, color, and width blocks.
- Same-platform repeatability of optimizer and render-rank semantic digests.
- Multi-scale/background resvg scores and deterministic winner records.
- Divergence/non-finite tests proving validated fallback behavior.
- Gate G4 ablation measuring fidelity gain, topology, node/path regressions, runtime, and RSS.
