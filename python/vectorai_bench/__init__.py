"""Benchmark orchestration package for VectorAI."""

from .manifest import (
    ManifestError,
    canonical_manifest_bytes,
    load_manifest,
    manifest_sha256,
    split_summary,
    validate_no_family_leakage,
    write_manifest,
)
from .models import (
    BenchmarkCase,
    DatasetManifest,
    DesignFamily,
    GeometryTruth,
    GroundTruth,
    ManifestValidationError,
    Point,
    PrimaryClass,
    SourceAsset,
    Split,
    TopologyTruth,
    Variant,
    VariantTier,
)

__all__ = [
    "BenchmarkCase",
    "DatasetManifest",
    "DesignFamily",
    "GeometryTruth",
    "GroundTruth",
    "ManifestError",
    "ManifestValidationError",
    "Point",
    "PrimaryClass",
    "SourceAsset",
    "Split",
    "TopologyTruth",
    "Variant",
    "VariantTier",
    "canonical_manifest_bytes",
    "load_manifest",
    "manifest_sha256",
    "split_summary",
    "validate_no_family_leakage",
    "write_manifest",
]
__version__ = "0.1.0"
