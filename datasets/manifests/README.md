# Dataset manifests

Only provenance, split, license, and content-addressed artifact manifests belong here. Source/customer raster data must not be committed by default.

Manifests conform to `schemas/dataset-manifest.schema.json`. `family_id` is the leakage boundary: all variants of one design family must remain in exactly one of `development`, `validation`, or `locked_test`. Artifact references are content-addressed and carry provenance plus `license_id`; generated or licensed payloads live outside Git.
