# ADR-013: Explicit physical cut-ready hard gate

- **Status:** Accepted for E6
- **Scope:** Generated stroke cut-outline SVG only; not arbitrary imported SVG
- **Review trigger:** Plotter feedback, physical scaling errors, or closed-ring outline union

## Context

A raster-sized, closed SVG outline is not automatically safe to send to a cutter. The manufacturing contract needs physical units and minimum mechanical feature sizes. The ordinary editability/stroke SVG must remain usable even when its optional cut outline is not cut-ready (for example an ambiguous ring with a self-crossing per-edge outline).

## Decision

Cut-ready is **opt-in** via `CutReadyPolicy` with explicit physical width and height in millimetres. The output uses `width="…mm" height="…mm"` while retaining the pixel-space `viewBox`; non-uniform physical scaling is rejected. The cut outline must consist of bounded, closed filled paths with `stroke="none"`. The graph/outline geometric validator must pass without crossings, duplicates or overlaps. Non-finite/non-positive widths, out-of-canvas geometry, quantized segments below `minimum_segment_mm`, and nonadjacent clearance below `minimum_gap_mm` are hard failures. The segment budget is fixed and bounded; invalid policy, empty geometry or oversized input fails closed. Normal stroke export and its ambiguity routing are unaffected if cut-ready is not requested. Only a passing opt-in job may set `cut_ready=true` in its manifest.

Topology remains a hard gate. A numerical penalty, SVG `Z` alone, a visually plausible preview or a renderer's clipping of an out-of-bounds contour never waives a cut finding. File validation is restricted to bounded generated SVG and rejects DTD/entities.

## Alternatives

- **Implicit physical size from SVG pixels:** Rejected; pixel density is not a manufacturing unit.
- **Automatic union of intersecting T/X or ring outlines:** Deferred pending deterministic planar-union implementation and closed-ring fidelity evidence. Unsafe contours instead fail cut-ready.
- **Soft warnings for short segments and gaps:** Rejected for manufacturing export.

## Consequences and evidence

Physical output may fail where standard E4 stroke/fill output succeeds. The caller must choose material-specific segment and clearance tolerances; defaults (`0.2 mm`, `0.4 mm`) are conservative examples, not a fabrication guarantee. Unit/pipeline tests cover size, aspect ratio, segment length, clearance, visible stroke, XML limits and crossing ring rejection. G3 normal mode continues to be tested independently.
