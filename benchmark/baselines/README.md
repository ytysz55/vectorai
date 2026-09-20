# Baseline adapters

Baseline executables are invoked as isolated, version-pinned processes. Their binaries and generated artifacts are not committed to this repository.

- `benchmark/configs/vtracer.lock.json` pins VTracer 0.6.4 archives, executable hashes, and `faithful`/`geometric`/`minimal` presets.
- `benchmark/configs/potrace.lock.json` pins Potrace 1.16 source/Windows artifacts and binary-only presets.
- VTracer remains a benchmark/candidate generator, not the product core.
- Potrace is GPL-isolated: external process only, PBM input only, no source copying, no `libpotrace` linkage, and no default redistribution.

Every adapter result records typed status, version, executable SHA-256, preset arguments, wall time, and output SHA-256. Missing tools, timeouts, invalid outputs, and version mismatches are recorded rather than silently skipped.
