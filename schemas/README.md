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

`fixtures/valid` must be accepted and `fixtures/invalid` must be rejected by the schema test suite.

Execution timings and peak memory are observational fields. They are not included when computing a semantic determinism digest; ADR-008 defines the canonical projection.
