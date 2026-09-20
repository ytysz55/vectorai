#pragma once

#include <cstddef>
#include <cstdint>
#include <vector>

#include "vectorai/core/boundary.hpp"
#include "vectorai/core/region_graph.hpp"
#include "vectorai/core/result.hpp"

namespace vectorai::binary {

enum class CandidateKind {
  kPolyline,
  kRectangle,
  kCircle,
  kEllipse,
  kRoundedRectangle,
  kBezier,
};

enum class SegmentKind {
  kLine,
  kCubic,
};

struct VectorSegment {
  SegmentKind kind{SegmentKind::kLine};
  Point2d start;
  Point2d control1;
  Point2d control2;
  Point2d end;
};

struct ShapeCandidate {
  CandidateKind kind{CandidateKind::kPolyline};
  std::vector<VectorSegment> segments;
  double fit_error{0.0};
  double complexity{0.0};
};

struct CycleCandidates {
  std::uint64_t cycle_id{0};
  std::vector<Point2d> points;
  std::vector<std::size_t> corner_indices;
  std::vector<ShapeCandidate> candidates;
};

struct FittingConfig {
  double corner_angle_degrees{30.0};
  double primitive_tolerance{0.75};
  double bezier_tolerance{0.35};
  std::size_t maximum_curve_span{64};
};

[[nodiscard]] std::vector<std::size_t> detect_corners(
    const std::vector<Point2d>& closed_points, double angle_degrees = 30.0);
[[nodiscard]] std::vector<ShapeCandidate> generate_primitive_candidates(
    const std::vector<Point2d>& closed_points, double tolerance = 0.75);
[[nodiscard]] Result<ShapeCandidate> fit_bezier_dp(const std::vector<Point2d>& closed_points,
                                                  double tolerance = 0.35,
                                                  std::size_t maximum_curve_span = 64U);
[[nodiscard]] Result<std::vector<CycleCandidates>> generate_candidates(
    const RegionGraph& graph, const BoundaryEvidence& evidence,
    const FittingConfig& config = {});

}  // namespace vectorai::binary
