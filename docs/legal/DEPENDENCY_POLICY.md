# Dependency, license, and baseline policy

**Status:** E0 policy  
**Applies to:** Native engine, Python tooling, local-first web application, benchmark tools, and distributed artifacts

This document is technical license hygiene, not legal advice. A qualified lawyer must review the final dependency graph, distribution model, benchmark permissions, and relevant patent claims before commercial release.

## Policy classes

### `allow`

The dependency may be evaluated for the stated component when:

- its exact version and source hash are pinned,
- its transitive dependencies are inventoried,
- required notices and license texts are distributed,
- its use remains within the recorded constraints.

`allow` is not blanket approval for a different version, feature set, or distribution model.

### `review`

The tool is not linked into the proprietary engine. Use is limited to research, CI, or an isolated baseline process until legal/ToS review approves more.

### `deny`

The code, library, feature, or model must not enter the proprietary product under the current plan. A commercial license or explicit policy change is required.

## Binding rules

1. No dependency is added without exact version, SPDX expression, source URL, purpose, linkage/distribution mode, and reviewer status.
2. The native E0 core remains dependency-free.
3. Ceres must be configured with `WITH_SUITESPARSE=OFF`.
4. SuiteSparse CHOLMOD/SPQR must not be linked without a commercial license decision.
5. Potrace source or libpotrace must not be copied or linked into the proprietary core.
6. Potrace may be evaluated only as an isolated benchmark executable. Redistribution conditions still require legal review and corresponding source/license obligations.
7. GPL applications used as external test or baseline tools must remain separate works; their binaries are not bundled by default.
8. Competitor SaaS output is not used for training, locked benchmarks, or product claims unless the service terms and written permission allow it.
9. Customer processing permission is separate from benchmark, retention, and training permission.
10. The release pipeline generates an SPDX/CycloneDX SBOM and a third-party notice package.
11. License files are stored verbatim for every distributed third-party component.
12. Optional build features are reviewed independently; a permissive top-level project can enable copyleft transitive code through a feature flag.

## Current decisions

| Component | Intended use | SPDX/license | Status | Constraint |
| --- | --- | --- | --- | --- |
| OpenCV | Native image processing | Apache-2.0 | allow | Exact version and transitive graph must be pinned. |
| Eigen | Native linear algebra | MPL-2.0 | allow | Preserve notices; review bundled source files. |
| Ceres Solver | Native continuous optimizer | Apache-2.0 | allow | `WITH_SUITESPARSE=OFF`; audit Abseil/glog and optional backends. |
| Clipper2 | Polygon validation/operations | BSL-1.0 | allow | Exact source/version and notice required. |
| pybind11 | Native/Python boundary | BSD-3-Clause | allow | Coarse-grained binding only. |
| resvg | Reference SVG renderer | MIT OR Apache-2.0 | allow | Pin executable/source and include selected license notice. |
| FastAPI | Localhost API | MIT | allow | Review full Python lock before distribution. |
| React | Local-first UI | MIT | allow | Review npm lock before distribution. |
| TypeScript | UI toolchain | Apache-2.0 | allow | Build-time tool; retain notices where required. |
| Tauri | Optional desktop wrapper | MIT OR Apache-2.0 | review | P2 only; WebView/platform dependencies require review. |
| VTracer | Benchmark baseline | MIT | allow | Baseline executable/config is version pinned. |
| PolyFit | Research reference | MIT | review | Do not import code before dependency-level audit. |
| PolyVectorization | Research reference | MIT | review | Line-art reference only; audit old dependencies. |
| Potrace/libpotrace | Binary baseline | GPL-2.0-or-later | review | External process only; never link/copy into core. |
| SuiteSparse CHOLMOD/SPQR | Ceres optional backend | GPL/commercial | deny | Commercial license required to change this decision. |
| CGAL GPL packages | Geometry dependency | Package-specific GPL/LGPL/commercial | deny | Not needed for P0; package-by-package review required. |
| Inkscape | Manual/CI baseline | GPL-3.0-or-later | review | Complete binary license per upstream COPYING; individual sources differ. External tool; no default bundling. |
| Chromium | Renderer compatibility oracle | BSD-3-Clause plus third-party | review | CI/system tool; no product bundling in P0. |
| Adobe Illustrator | Manual baseline | Proprietary | review | Licensed operator and documented preset/version only. |
| Vectorizer.AI | Competitor benchmark | Proprietary service terms | review | Written/ToS permission required. |

The machine-readable source of this table is `third_party/dependencies.json`.

## Release gate

A release fails if:

- a distributed dependency has `version: not-selected`,
- a distributed entry is `review` or `deny`,
- an entry lacks SPDX/source/license text,
- lockfiles and the inventory disagree,
- Ceres enables SuiteSparse,
- the notice generator reports missing license text,
- dataset or benchmark provenance is incomplete.
