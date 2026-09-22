# ADR-012: Fill/stroke arbitration

- **Status:** Accepted for E4
- **Scope:** Line-art routing, fill/stroke candidate generation, model selection, confidence, and export
- **Review trigger:** Gate G3 regression, real-pilot routing confusion, or calibrated confidence work

## Context

The same raster region may be represented as a filled outline or as a centerline with width, cap, and join semantics. A premature binary routing decision can destroy holes, merge junctions, or create an unnecessarily dense SVG. Conversely, always exporting strokes can misrepresent compact logos, closed rings, and variable-width silhouettes.

The engine therefore needs a deterministic policy that preserves topology, compares both representations when evidence is weak, and exposes uncertainty instead of presenting an arbitrary semantic choice as fact.

## Decision

### Routing evidence

Routing v1 uses deterministic geometric evidence from the foreground mask:

- normalized thickness,
- bounding-box occupancy,
- perimeter/area ratio,
- aspect ratio,
- active-pixel support,
- hole presence.

The classifier emits `fill`, `stroke`, or `ambiguous`, plus a stroke score, confidence, reasons, and a fallback. It is a routing prior, not a hard topology decision.

### Hard topology policy

Fill and stroke hypotheses are rejected before scoring if they change required foreground component connectivity. Junction valence and hole semantics are measured separately. A lower render error cannot compensate for a topology failure.

The topology graph is immutable during arbitration. Spur removal may delete only bounded endpoint-to-junction branches below the configured length and must merge the resulting degree-two chains deterministically.

### Dual-hypothesis comparison

When a stroke graph is feasible, the engine produces both:

1. a fill hypothesis through the multicolor fill pipeline;
2. stroke hypotheses over bounded cap/join and width models.

Candidates use the same reference renderer and are ranked by:

1. hard topology validity;
2. fidelity band;
3. editability/complexity;
4. routing prior;
5. stable candidate identifier.

If a stroke candidate is within `0.02` premultiplied RGBA RMSE of fill and has fewer nodes, stroke wins the Pareto decision. Outside that fidelity band, the lower-error valid candidate wins. Runtime and RSS are observational and never enter the semantic digest.

### Ambiguity and fallback

A score inside the routing dead band produces `ambiguous` and `needs_review`. Closed rings with stroke-like thickness are deliberately ambiguous because a filled annulus and a closed stroke can be raster-equivalent. Their safe fallback is fill, while both hypotheses remain available in artifacts.

Cap/join recovery is evaluated by renderer equivalence, not label identity alone. Raster-equivalent style candidates within `0.002` RMSE of the best style satisfy the golden; the selected candidate still uses a deterministic stable-ID tie-break.

### Width models

Width is sampled from a deterministic chamfer distance field along the centerline. Robust 10th–90th percentile variation prevents endpoint/corner outliers from forcing a variable-width model. Constant width is preferred when robust variation and MAE remain within configured bounds; otherwise a variable-width closed outline is emitted.

### Export

- Constant-width hypotheses export explicit SVG `stroke-width`, `stroke-linecap`, and `stroke-linejoin`.
- Variable-width hypotheses export closed filled outlines.
- Cut-outline export always uses closed filled paths with no visible stroke.
- Coordinates use ADR-011 pixel-center and deterministic serialization rules.

## Alternatives considered

### Route once and never compare

Rejected. Low-resolution rings, caps, and junctions are not always semantically identifiable from raster evidence.

### Always choose the lowest RMSE

Rejected. A dense filled outline can have slightly lower raster error while being substantially less editable than an equivalent two-node stroke.

### Always choose stroke for thin regions

Rejected. Thin filled ornaments and closed rings would be mislabeled, and variable-width forms may not have faithful SVG stroke semantics.

### Learned classifier in E4

Deferred. The current locked synthetic corpus is too small for a calibrated model. The deterministic feature model establishes a measurable baseline and preserves local-first CPU behavior.

## Consequences

- Stroke routing is explainable and byte-deterministic.
- Ambiguous inputs remain honest `needs_review` results.
- Fill and stroke share topology, fidelity, and complexity metrics.
- Renderer calls increase in the heavy stroke path because bounded style candidates are compared.
- Real pilot data is still required before interpreting confidence as probability.

## Validation evidence required

- Fill/stroke confusion matrix including a closed-ring ambiguity case.
- Exact line/T/X connectivity and junction valence.
- Centerline p95 and width error on locked synthetic fixtures.
- Butt/round/square and miter/round/bevel renderer-equivalence goldens.
- Positive node advantage against the fill branch in the same fidelity band.
- Closed cut-outline validation.
- Repeated Gate G3 semantic digest.
