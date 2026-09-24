# ADR-017: Local observability and privacy defaults

- **Status:** Accepted for E6
- **Scope:** E3/E4 product run bundles, JSONL stage events and schema-valid manifests
- **Review trigger:** Remote deployment proposal, telemetry request or new debug data class

## Context

A local-first image processor needs reproducible diagnostics without turning user graphics or filenames into telemetry. Timing, memory and machine observations are not semantic output identity.

## Decision

Each successful product run writes a bounded `events.jsonl` with ordered `STAGE_STARTED`/`STAGE_COMPLETED` codes and stage duration observations. Events do not contain source pixels, input paths, user text, renderer stderr, or source fingerprints by default. `debug_opt_in` only adds the source SHA-256 to event records; it does not include original bytes or paths. Stable fallback codes replace exception messages in default diagnostics. Auxiliary renderer messages are reduced to status unless opted in. Logs remain local and no network telemetry is introduced.

`run-manifest.json` follows `run-manifest.schema.json` v1: input/source and artifact SHA-256, engine/build/commit, config/profile hash, Windows/Linux platform metadata, dependency versions, stage outcomes/durations, sampled process-RSS observation, summary, stable-code findings and ordered artifact references. The manifest intentionally carries source and artifact hashes as a **local** audit artifact; it must not be uploaded or logged as an event without explicit consent. Runtime/RSS, OS and git state are excluded from locked semantic digests. The product manifest preserves existing renderer/seam observations without serializing executable paths.

The engine only reports an output as `cut_ready` after all strict physical/geometry gates pass. Unsupported OS/architecture and unknown event stage names fail closed.

## Alternatives and consequences

Free-form exception text and absolute paths in default logs were rejected. A process RSS sample is reported as an observation and may underestimate the true high-water mark on Linux; it is not a hard resource-limit measurement. A build without Git metadata uses a zero digest and marks itself dirty rather than claiming a known commit. Stage start/finish events are emitted after completion of a successful atomic run; crash-before-manifest forensic logging is a separate future concern. Events and manifests have tests for JSON schema, privacy redaction, determinism and fallback behavior.
