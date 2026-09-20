#include "vectorai/core/boundary.hpp"

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <limits>
#include <string>
#include <utility>
#include <vector>

namespace vectorai::binary {
namespace {

[[nodiscard]] EngineError boundary_error(ErrorCode code, std::string message) {
  EngineError error;
  error.code = code;
  error.stage = Stage::kBoundary;
  error.message = std::move(message);
  return error;
}

[[nodiscard]] float sample_nearest(const GrayImage& image, Point2d point) {
  const double clamped_x =
      std::clamp(point.x, 0.0, static_cast<double>(image.width) - 1.0e-9);
  const double clamped_y =
      std::clamp(point.y, 0.0, static_cast<double>(image.height) - 1.0e-9);
  const auto x = static_cast<std::size_t>(std::floor(clamped_x));
  const auto y = static_cast<std::size_t>(std::floor(clamped_y));
  return image.at(x, y);
}

[[nodiscard]] float sample_reliability(const std::vector<float>& confidence,
                                       const GrayImage& image, Point2d point) {
  if (confidence.empty()) {
    return 1.0F;
  }
  const double clamped_x =
      std::clamp(point.x, 0.0, static_cast<double>(image.width) - 1.0e-9);
  const double clamped_y =
      std::clamp(point.y, 0.0, static_cast<double>(image.height) - 1.0e-9);
  const auto x = static_cast<std::size_t>(std::floor(clamped_x));
  const auto y = static_cast<std::size_t>(std::floor(clamped_y));
  return confidence[y * image.width + x];
}

}  // namespace

Result<BoundaryEvidence> estimate_boundaries(const RegionGraph& graph, const GrayImage& image,
                                             const std::vector<float>& reliability_confidence,
                                             const BoundaryConfig& config) {
  auto graph_validation = validate_region_graph(graph);
  if (!graph_validation) {
    return Result<BoundaryEvidence>::failure(graph_validation.error());
  }
  if (image.width == 0U || image.height == 0U || image.width > kMaxPixels ||
      image.height > kMaxPixels || image.width > kMaxPixels / image.height ||
      image.foreground_evidence.size() != image.width * image.height) {
    return Result<BoundaryEvidence>::failure(boundary_error(
        ErrorCode::kInternalInvariantViolation, "boundary image dimensions are invalid"));
  }
  if (!reliability_confidence.empty() &&
      reliability_confidence.size() != image.foreground_evidence.size()) {
    return Result<BoundaryEvidence>::failure(boundary_error(
        ErrorCode::kInternalInvariantViolation, "reliability size does not match image"));
  }
  if (!std::isfinite(config.threshold) || config.threshold < 0.0F || config.threshold > 1.0F ||
      !std::isfinite(config.minimum_contrast) || config.minimum_contrast < 0.0F) {
    return Result<BoundaryEvidence>::failure(
        boundary_error(ErrorCode::kInternalInvariantViolation, "boundary config is invalid"));
  }
  for (const float value : image.foreground_evidence) {
    if (!std::isfinite(value) || value < 0.0F || value > 1.0F) {
      return Result<BoundaryEvidence>::failure(boundary_error(
          ErrorCode::kInternalInvariantViolation, "foreground evidence is outside [0, 1]"));
    }
  }
  for (const float value : reliability_confidence) {
    if (!std::isfinite(value) || value < 0.0F || value > 1.0F) {
      return Result<BoundaryEvidence>::failure(boundary_error(
          ErrorCode::kInternalInvariantViolation, "reliability confidence is outside [0, 1]"));
    }
  }

  BoundaryEvidence evidence;
  evidence.subpixel_enabled = config.enable_subpixel;
  evidence.samples.reserve(graph.canonical_edge_count);
  for (const HalfEdge& edge : graph.half_edges) {
    if (edge.face != 1U) {
      continue;
    }
    const GridPoint origin = graph.vertices[edge.origin].position;
    const GridPoint target = graph.vertices[edge.target].position;
    const double dx = static_cast<double>(target.x - origin.x);
    const double dy = static_cast<double>(target.y - origin.y);
    const Point2d midpoint{(static_cast<double>(origin.x) + static_cast<double>(target.x)) * 0.5,
                           (static_cast<double>(origin.y) + static_cast<double>(target.y)) * 0.5};
    const Point2d tangent{dx, dy};
    const Point2d outward{dy, -dx};
    const Point2d inside{midpoint.x - 0.5 * outward.x, midpoint.y - 0.5 * outward.y};
    const Point2d outside{midpoint.x + 0.5 * outward.x, midpoint.y + 0.5 * outward.y};
    const float inside_value = sample_nearest(image, inside);
    const float outside_value = sample_nearest(image, outside);
    const double contrast =
        std::abs(static_cast<double>(inside_value) - static_cast<double>(outside_value));
    double offset = 0.0;
    if (config.enable_subpixel && contrast >= static_cast<double>(config.minimum_contrast)) {
      const double denominator =
          static_cast<double>(inside_value) - static_cast<double>(outside_value);
      const double fraction =
          (static_cast<double>(inside_value) - static_cast<double>(config.threshold)) / denominator;
      offset = std::clamp(-0.5 + fraction, -0.5, 0.5);
    }
    const float inside_reliability = sample_reliability(reliability_confidence, image, inside);
    const float outside_reliability = sample_reliability(reliability_confidence, image, outside);
    const double reliability =
        0.5 * (static_cast<double>(inside_reliability) +
               static_cast<double>(outside_reliability));
    const bool junction = graph.vertices[edge.origin].outgoing_half_edges.size() > 2U ||
                          graph.vertices[edge.target].outgoing_half_edges.size() > 2U;
    const double predicted_threshold =
        static_cast<double>(inside_value) +
        (offset + 0.5) *
            (static_cast<double>(outside_value) - static_cast<double>(inside_value));
    BoundarySample sample;
    sample.canonical_edge = edge.canonical_edge;
    sample.pixel_edge_position = midpoint;
    sample.position = Point2d{midpoint.x + offset * outward.x,
                              midpoint.y + offset * outward.y};
    sample.tangent = tangent;
    sample.outward_normal = outward;
    sample.covariance_normal = 0.01 + (1.0 - reliability) * 0.24 + (1.0 - contrast) * 0.10;
    sample.residual = std::abs(predicted_threshold - static_cast<double>(config.threshold));
    sample.source_support = contrast * reliability;
    sample.subpixel_offset = offset;
    sample.junction_excluded = junction;
    evidence.samples.push_back(sample);
  }
  std::sort(evidence.samples.begin(), evidence.samples.end(),
            [](const BoundarySample& left, const BoundarySample& right) {
              return left.canonical_edge < right.canonical_edge;
            });
  if (evidence.samples.size() != graph.canonical_edge_count) {
    return Result<BoundaryEvidence>::failure(boundary_error(
        ErrorCode::kInsufficientBoundaryEvidence,
        "not every canonical boundary edge produced exactly one evidence sample"));
  }
  return Result<BoundaryEvidence>::success(std::move(evidence));
}

}  // namespace vectorai::binary
