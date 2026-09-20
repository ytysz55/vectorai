#pragma once

#include <cstdint>
#include <map>
#include <string>
#include <string_view>
#include <vector>

namespace vectorai {

enum class ErrorCode {
  kUnsupportedInput,
  kDecodeError,
  kResourceLimit,
  kInvalidColorProfile,
  kAmbiguousAlpha,
  kPaletteAmbiguous,
  kTopologyAmbiguous,
  kNonManifoldGraph,
  kInsufficientBoundaryEvidence,
  kNoFeasibleCandidate,
  kStrokeAmbiguous,
  kOptimizerDiverged,
  kExportFailed,
  kValidationFailed,
  kRendererDisagreement,
  kInternalInvariantViolation,
};

enum class Stage {
  kUnknown,
  kDecode,
  kNormalize,
  kReliability,
  kPalette,
  kSegmentation,
  kTopology,
  kBoundary,
  kCandidateGeneration,
  kStroke,
  kModelSelection,
  kOptimization,
  kRenderAndRank,
  kExport,
  kValidation,
};

enum class RunStatus {
  kSuccess,
  kDegraded,
  kNeedsReview,
  kUnsupported,
  kFailed,
};

[[nodiscard]] std::string_view to_string(ErrorCode code) noexcept;
[[nodiscard]] std::string_view to_string(Stage stage) noexcept;
[[nodiscard]] std::string_view to_string(RunStatus status) noexcept;

struct EngineError {
  ErrorCode code{ErrorCode::kInternalInvariantViolation};
  Stage stage{Stage::kUnknown};
  std::string message;
  bool retryable{false};
  std::vector<std::uint64_t> entity_ids;
  std::map<std::string, std::string> context;
};

}  // namespace vectorai
