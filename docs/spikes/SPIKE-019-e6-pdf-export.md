# SPIKE-019 — E6 PDF export backend decision

**Outcome:** PDF is excluded from E6; validated SVG remains the only supported release/cut-ready vector format. See [ADR-009](../adr/ADR-009-pdf-export-scope.md).

## Local scale/vector-content experiment

- Input: validated stroke-join-round cut-outline path from `out/stroke-g3-e6-cut/runs/stroke-join-round/cut-outline.svg`, in a 128 × 128 user-unit viewBox. For this *experimental* export its SVG viewport was set to `width="32mm" height="32mm"` without modifying the path.
- Tool: external, local Inkscape 1.4.2 CLI with `--export-type=pdf --export-filename=...`. Outputs (ignored by Git): `out/e6-pdf-spike/32mm-cut.svg`, `out/e6-pdf-spike/32mm-cut.pdf`.
- Inspection: PDF 1.5, one page `/MediaBox [ 0 0 90.708661 90.708661 ]` (32 mm at 72 pt/in, absolute discrepancy < 0.000001 pt). Inflated content stream contains `m`, `l`, `h`, `f` vector commands, no embedded raster image operator. The page objects are compressed, so naive raw-byte searches for `/MediaBox` are **not** a sound PDF inspector; this observation was made on the decompressed object stream.
- **Not verified:** PDF path-level topology, stroke-free property under another PDF renderer, negative/complex cut fixtures, PDF-to-PNG renderer agreement, reproducible PDF bytes, or supported Windows/Linux distribution. This spot check cannot pass a PDF release gate.

## Backend and license assessment

| Candidate | Feasibility | Release decision |
|---|---|---|
| Unbundled Inkscape subprocess | Observed vector PDF and correct millimetre scale for one local sample; [Inkscape license](https://inkscape.org/about/license/) is GNU GPL, [CLI export flags](https://inkscape.org/doc/man/inkscape-man.html) documented. | Local experiment only. No bundled dependency or automatic export; review redistribution and validate PDF semantics first. |
| CairoSVG | [Official docs](https://cairosvg.org/documentation/) support SVG-to-PDF, LGPLv3 and Cairo runtime. | Deferred: new dependency and no locked fixture parity/scale/legal review. |
| resvg | CLI [rasterizes SVG to PNG](https://manpages.ubuntu.com/manpages/resolute/man1/resvg.1.html). | Not a PDF backend. |
| Raster image inside PDF | Preserves appearance but destroys editable cut contours. | Rejected. |

**Decision criterion:** E6 EXP-001 requires a documented license/measurement/renderer decision, not necessarily PDF shipment. The vector scale spot check passed; PDF renderer/path agreement is unproven, therefore the release stays SVG-only. A future PDF effort must gate measured physical dimensions, vector path geometry/closure, deterministic file semantics, license/inventory, sandboxed export, and independent PDF render parity before enabling PDF in the API.
