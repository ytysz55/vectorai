#include "vectorai/core/error.hpp"

namespace vectorai {

std::string_view to_string(const ErrorCode code) noexcept {
  switch (code) {
    case ErrorCode::kUnsupportedInput:
      return "UNSUPPORTED_INPUT";
    case ErrorCode::kDecodeError:
      return "DECODE_ERROR";
    case ErrorCode::kResourceLimit:
      return "RESOURCE_LIMIT";
    case ErrorCode::kInvalidColorProfile:
      return "INVALID_COLOR_PROFILE";
    case ErrorCode::kAmbiguousAlpha:
      return "AMBIGUOUS_ALPHA";
    case ErrorCode::kPaletteAmbiguous:
      return "PALETTE_AMBIGUOUS";
    case ErrorCode::kTopologyAmbiguous:
      return "TOPOLOGY_AMBIGUOUS";
    case ErrorCode::kNonManifoldGraph:
      return "NON_MANIFOLD_GRAPH";
    case ErrorCode::kInsufficientBoundaryEvidence:
      return "INSUFFICIENT_BOUNDARY_EVIDENCE";
    case ErrorCode::kNoFeasibleCandidate:
      return "NO_FEASIBLE_CANDIDATE";
    case ErrorCode::kStrokeAmbiguous:
      return "STROKE_AMBIGUOUS";
    case ErrorCode::kOptimizerDiverged:
      return "OPTIMIZER_DIVERGED";
    case ErrorCode::kExportFailed:
      return "EXPORT_FAILED";
    case ErrorCode::kValidationFailed:
      return "VALIDATION_FAILED";
    case ErrorCode::kRendererDisagreement:
      return "RENDERER_DISAGREEMENT";
    case ErrorCode::kInternalInvariantViolation:
      return "INTERNAL_INVARIANT_VIOLATION";
  }
  return "INTERNAL_INVARIANT_VIOLATION";
}

std::string_view to_string(const Stage stage) noexcept {
  switch (stage) {
    case Stage::kUnknown:
      return "unknown";
    case Stage::kDecode:
      return "decode";
    case Stage::kNormalize:
      return "normalize";
    case Stage::kReliability:
      return "reliability";
    case Stage::kPalette:
      return "palette";
    case Stage::kSegmentation:
      return "segmentation";
    case Stage::kTopology:
      return "topology";
    case Stage::kBoundary:
      return "boundary";
    case Stage::kCandidateGeneration:
      return "candidate_generation";
    case Stage::kStroke:
      return "stroke";
    case Stage::kModelSelection:
      return "model_selection";
    case Stage::kOptimization:
      return "optimization";
    case Stage::kRenderAndRank:
      return "render_and_rank";
    case Stage::kExport:
      return "export";
    case Stage::kValidation:
      return "validation";
  }
  return "unknown";
}

std::string_view to_string(const RunStatus status) noexcept {
  switch (status) {
    case RunStatus::kSuccess:
      return "success";
    case RunStatus::kDegraded:
      return "degraded";
    case RunStatus::kNeedsReview:
      return "needs_review";
    case RunStatus::kUnsupported:
      return "unsupported";
    case RunStatus::kFailed:
      return "failed";
  }
  return "failed";
}

}  // namespace vectorai
