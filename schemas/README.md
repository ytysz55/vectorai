# VectorAI data contracts

All public JSON artifacts use JSON Schema draft 2020-12 and carry an explicit `schema_version`.

| Schema | Purpose |
| --- | --- |
| `engine-config.schema.json` | Versioned mode, determinism, output, and resource-limit request |
| `run-manifest.schema.json` | Reproducibility identity, platform, stage, resource, warning, fallback, and artifact record |
| `validation-report.schema.json` | Ordered hard/soft validation gate results |
| `benchmark-record.schema.json` | Family-safe dataset case, runner, metric, and artifact record |
| `dataset-manifest.schema.json` | Family provenance, split, ground-truth, and degradation case contract |
| `e2-g1-report.schema.json` | Binary gate metrics, ablations, baseline comparison, and verdict |
| `multicolor-g2-report.schema.json` | Multicolor topology, fidelity, seam, node, and renderer evidence |
| `stroke-g3-report.schema.json` | Stroke routing, centerline, width, style, cut-outline, and gate verdict |
| `optimizer-profiles.schema.json` | Four-mode E5 objective weights, bounded refinement, and render-rank policy |
| `optimizer-g4-report.schema.json` | E5 ablation, topology, fidelity, node, runtime, and continuation verdict |
| `e6-release-report.schema.json` | G2/G3/G4 repeat digests and pairwise white-matte renderer release evidence |
| `local-job.schema.json` | E7 loopback job lifecycle, typed error, and published artifact status |

`fixtures/valid` must be accepted and `fixtures/invalid` must be rejected by the schema test suite.

Execution timings and peak memory are observational fields. They are not included when computing a semantic determinism digest; ADR-008 defines the canonical projection.
