# SPIKE-017: E5 heavy-path runtime profile

- **Status:** Complete
- **Date:** 2026-09-23
- **Scope:** Locked 17-case multicolor G4 corpus, minimal profile, pinned resvg 0.47.0
- **Artifact:** `out/optimizer-g4-profile/g4-report.json`

## Question

Would replacing the solver-independent Python optimizer with Ceres materially improve the observed E5 heavy-path runtime?

## Instrumentation

`optimize_multicolor_hypotheses()` records observational timings for:

1. topology-safe scene selection;
2. SVG export and editability measurement;
3. normalized objective evaluation;
4. Top-K multi-scale/background resvg ranking;
5. total optimization path.

These values are written to G4 reports but excluded from the semantic digest. Runtime-dependent gate verdict fields are also excluded from that digest.

## Observation

Across the 17 locked cases:

| Stage | Sum | Share of measured optimizer time | Median case |
| --- | ---: | ---: | ---: |
| Scene selection | 4.440 s | 1.84% | 82 ms |
| SVG export/editability | 0.541 s | 0.22% | 16 ms |
| Objective calculation | 0.005 s | <0.01% | <1 ms |
| resvg render-and-rank | 235.987 s | 97.90% | 2.298 s |
| Total | 241.049 s | 100% | 2.407 s |

Representative cases dominate the tail because every Top-K candidate is rendered at `0.5x`, `1x`, `2x`, and `4x`. The largest observed case spent about `52.2 s` in render-and-rank versus `1.2 s` in scene selection. The same corpus had previously met the 20-second target on a faster run, showing that wall time is observational and host/load sensitive.

## Follow-up optimization

The profile exposed two avoidable costs in the oracle implementation:

- byte-identical SVG hypotheses were rendered and scored repeatedly;
- every comparison rebuilt reference compositing and used allocation-heavy float conversions.

The oracle now hashes SVG payloads, renders and scores each unique payload once, reuses prepared reference data, uses byte-exact compositing lookup tables, and performs allocation-bounded RMSE aggregation. The minimal profile keeps the hard-valid baseline plus the two best analytic candidates (`top_k = 3`). The full four-scale/four-background matrix remains unchanged for every finalist.

Two final locked runs passed with the same semantic digest `cfb197b194c2a14a64e49748988e6cbce53f269c01f2c6ccbabf38480111d81a`. Optimizer-path p95 fell to `4.79 s` and `4.27 s`. The real continuous palette evaluator was connected to the production path and consumed at most `46 ms` per case. In the first run, aggregate measured optimizer time was:

| Stage | Sum | Share |
| --- | ---: | ---: |
| Scene selection | 4.310 s | 22.84% |
| SVG export/editability | 0.686 s | 3.63% |
| Continuous palette refinement | 0.277 s | 1.47% |
| Candidate objective calculation | 0.004 s | 0.02% |
| resvg render-and-rank | 13.539 s | 71.72% |
| Total | 18.878 s | 100% |

The earlier profile remains useful as the bottleneck diagnosis; the follow-up confirms that renderer-oracle implementation, not solver execution, controlled end-to-end latency.

## Decision

A Ceres port of the existing test-only `optimize_parameters()` path would not address the current bottleneck. The production E5 path performs discontinuous primitive-tolerance enumeration and spends approximately 98% of measured optimizer time in the final resvg oracle.

Before adding Ceres:

1. connect a real continuous scene parameterization to the solver-independent contract;
2. reduce render-oracle work without weakening the final decision, for example through staged scale escalation, deduplication of byte-identical SVG candidates, and analytic pre-ranking;
3. keep the pinned full multi-scale/background matrix for finalists and G4 evidence;
4. then measure whether solver time is large enough for Ceres to provide end-to-end value.

Ceres remains authorized as an optional quality/offline backend, but dependency integration is blocked on a production continuous evaluator. The Python backend remains the parity reference.
