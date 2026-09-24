# SPIKE-018 — E6 geometry validation foundation

## Implemented

The E6 foundation validates trusted scene/graph data before multicolor SVG export and stroke candidate rendering. Checks cover half-edge/twin/predecessor/cycle/ownership consistency, recomputed adjacency and planar boundary-cycle Euler accounting, stroke node/edge incidence and lengths, quantized contour closure, zero-length/duplicate segments, intersections, collinear overlaps, filled-face containment, and opposite-orientation shared segments. A graph-declared adjacency with no matching reversed scene segment is a hard gap. Presentation-only 2 px seam-cover strokes are **not** geometric boundaries. Both pipeline bundles include a schema-valid `validation-report.json` linked in the run manifest; hard failures use typed `VALIDATION_FAILED` errors. Report content is deterministic and excludes machine observations.

G3 and G4 locked repeated runs still pass with their previous semantic digests (`329d630a7bf009abb5b27fc30fa1224304b5508bccd4d3ca54b62caa42ecfb2d`, `cfb197b194c2a14a64e49748988e6cbce53f269c01f2c6ccbabf38480111d81a`). The `chat.png` minimal bundle passes the new validator.

## Remaining VAL-001 work

This is **not** yet a complete exported-geometry proof. The validator checks scene cycles and centerline graph, but does not flatten or inspect isolated smoothed Bézier/primitive paths, variable-width stroke outline polygons, or every cut-outline contour. The existing cut-outline XML closure/stroke check remains in place. Matching at least one reversed segment for a declared face pair does not prove complete coverage of its shared chain. Soft near-coincident/curve-contact review classification and a release-level all-renderer geometry agreement report are also pending. Do not promote this foundation to a general arbitrary-SVG validator or claim VAL-001 complete until those gaps and corresponding negative fixtures are addressed.

Topology is a hard eligibility gate; no fidelity or node gain can compensate for a hard geometric finding. Renderer disagreement is a separate observation and never substitutes for graph/scene validation.
