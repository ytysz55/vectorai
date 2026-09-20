#include "vectorai/core/model_selection.hpp"

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <limits>
#include <string>
#include <tuple>
#include <utility>
#include <vector>

namespace vectorai::binary {
namespace {

constexpr double kEpsilon = 1.0e-8;

[[nodiscard]] EngineError selection_error(ErrorCode code, std::string message) {
  EngineError error;
  error.code = code;
  error.stage = Stage::kModelSelection;
  error.message = std::move(message);
  return error;
}

[[nodiscard]] double distance_squared(Point2d left, Point2d right) {
  const double dx = left.x - right.x;
  const double dy = left.y - right.y;
  return dx * dx + dy * dy;
}

[[nodiscard]] Point2d cubic_at(const VectorSegment& segment, double parameter) {
  const double inverse = 1.0 - parameter;
  const double inverse_squared = inverse * inverse;
  const double parameter_squared = parameter * parameter;
  return Point2d{
      inverse_squared * inverse * segment.start.x +
          3.0 * inverse_squared * parameter * segment.control1.x +
          3.0 * inverse * parameter_squared * segment.control2.x +
          parameter_squared * parameter * segment.end.x,
      inverse_squared * inverse * segment.start.y +
          3.0 * inverse_squared * parameter * segment.control1.y +
          3.0 * inverse * parameter_squared * segment.control2.y +
          parameter_squared * parameter * segment.end.y,
  };
}

[[nodiscard]] double orientation(Point2d first, Point2d second, Point2d third) {
  return (second.x - first.x) * (third.y - first.y) -
         (second.y - first.y) * (third.x - first.x);
}

[[nodiscard]] bool on_segment(Point2d first, Point2d second, Point2d point) {
  return point.x >= std::min(first.x, second.x) - kEpsilon &&
         point.x <= std::max(first.x, second.x) + kEpsilon &&
         point.y >= std::min(first.y, second.y) - kEpsilon &&
         point.y <= std::max(first.y, second.y) + kEpsilon;
}

[[nodiscard]] bool segments_intersect(Point2d a, Point2d b, Point2d c, Point2d d) {
  const double abc = orientation(a, b, c);
  const double abd = orientation(a, b, d);
  const double cda = orientation(c, d, a);
  const double cdb = orientation(c, d, b);
  if (((abc > kEpsilon && abd < -kEpsilon) ||
       (abc < -kEpsilon && abd > kEpsilon)) &&
      ((cda > kEpsilon && cdb < -kEpsilon) ||
       (cda < -kEpsilon && cdb > kEpsilon))) {
    return true;
  }
  return (std::abs(abc) <= kEpsilon && on_segment(a, b, c)) ||
         (std::abs(abd) <= kEpsilon && on_segment(a, b, d)) ||
         (std::abs(cda) <= kEpsilon && on_segment(c, d, a)) ||
         (std::abs(cdb) <= kEpsilon && on_segment(c, d, b));
}

[[nodiscard]] bool has_self_intersection(const ShapeCandidate& candidate) {
  std::vector<Point2d> points;
  points.reserve(candidate.segments.size() * 8U + 1U);
  points.push_back(candidate.segments.front().start);
  for (const VectorSegment& segment : candidate.segments) {
    if (segment.kind == SegmentKind::kLine) {
      points.push_back(segment.end);
      continue;
    }
    constexpr std::size_t subdivisions = 8U;
    for (std::size_t step = 1U; step <= subdivisions; ++step) {
      points.push_back(cubic_at(segment,
                                static_cast<double>(step) /
                                    static_cast<double>(subdivisions)));
    }
  }
  const std::size_t segment_count = points.size() - 1U;
  for (std::size_t first = 0U; first < segment_count; ++first) {
    for (std::size_t second = first + 1U; second < segment_count; ++second) {
      const bool adjacent = second == first + 1U ||
                            (first == 0U && second + 1U == segment_count);
      if (adjacent) {
        continue;
      }
      if (segments_intersect(points[first], points[first + 1U], points[second],
                             points[second + 1U])) {
        return true;
      }
    }
  }
  return false;
}

[[nodiscard]] bool finite_point(Point2d point) {
  return std::isfinite(point.x) && std::isfinite(point.y);
}

[[nodiscard]] bool closed_candidate(const ShapeCandidate& candidate) {
  if (candidate.segments.empty()) {
    return false;
  }
  for (std::size_t index = 0U; index < candidate.segments.size(); ++index) {
    const VectorSegment& segment = candidate.segments[index];
    const VectorSegment& next = candidate.segments[(index + 1U) % candidate.segments.size()];
    if (!finite_point(segment.start) || !finite_point(segment.control1) ||
        !finite_point(segment.control2) || !finite_point(segment.end) ||
        distance_squared(segment.end, next.start) > kEpsilon * kEpsilon) {
      return false;
    }
  }
  return true;
}

[[nodiscard]] double endpoint_area(const ShapeCandidate& candidate) {
  double twice_area = 0.0;
  for (const VectorSegment& segment : candidate.segments) {
    twice_area += segment.start.x * segment.end.y - segment.end.x * segment.start.y;
  }
  return 0.5 * twice_area;
}

[[nodiscard]] bool is_primitive(CandidateKind kind) {
  return kind == CandidateKind::kRectangle || kind == CandidateKind::kCircle ||
         kind == CandidateKind::kEllipse || kind == CandidateKind::kRoundedRectangle;
}

[[nodiscard]] double score_candidate(const ShapeCandidate& candidate,
                                     const ModelSelectionConfig& config) {
  double score = config.fidelity_weight * candidate.fit_error +
                 config.complexity_weight * candidate.complexity;
  if (is_primitive(candidate.kind)) {
    score -= config.primitive_bonus;
  }
  return score;
}

}  // namespace

Result<void> validate_selected_model(const SelectedModel& model) {
  if (model.shapes.size() != model.topology.components + model.topology.holes) {
    return Result<void>::failure(selection_error(
        ErrorCode::kTopologyAmbiguous,
        "selected path count does not match component plus hole topology"));
  }
  if (!std::isfinite(model.objective)) {
    return Result<void>::failure(selection_error(
        ErrorCode::kInternalInvariantViolation, "selected objective is not finite"));
  }
  for (const ShapeCandidate& shape : model.shapes) {
    if (!closed_candidate(shape) || std::abs(endpoint_area(shape)) <= kEpsilon ||
        has_self_intersection(shape) || !std::isfinite(shape.fit_error) ||
        shape.fit_error < 0.0 ||
        !std::isfinite(shape.complexity) || shape.complexity < 0.0) {
      return Result<void>::failure(selection_error(
          ErrorCode::kTopologyAmbiguous,
          "selected shape is open, degenerate, or has invalid numeric state"));
    }
  }
  return Result<void>::success();
}

Result<SelectedModel> select_model(const std::vector<CycleCandidates>& cycles,
                                   const TopologySummary& topology,
                                   const ModelSelectionConfig& config) {
  if (cycles.size() != topology.components + topology.holes) {
    return Result<SelectedModel>::failure(selection_error(
        ErrorCode::kTopologyAmbiguous,
        "candidate cycle count differs from segmentation topology"));
  }
  if (!std::isfinite(config.fidelity_weight) || config.fidelity_weight < 0.0 ||
      !std::isfinite(config.complexity_weight) || config.complexity_weight < 0.0 ||
      !std::isfinite(config.primitive_bonus) || config.primitive_bonus < 0.0 ||
      !std::isfinite(config.maximum_fit_error) || config.maximum_fit_error < 0.0 ||
      config.maximum_segments_per_shape == 0U) {
    return Result<SelectedModel>::failure(selection_error(
        ErrorCode::kInternalInvariantViolation, "model selection config is invalid"));
  }

  SelectedModel model;
  model.topology = topology;
  model.shapes.reserve(cycles.size());
  for (const CycleCandidates& cycle : cycles) {
    const ShapeCandidate* best_candidate = nullptr;
    std::tuple<double, std::size_t, int> best_key{
        std::numeric_limits<double>::infinity(), std::numeric_limits<std::size_t>::max(),
        std::numeric_limits<int>::max()};
    for (const ShapeCandidate& candidate : cycle.candidates) {
      if (!closed_candidate(candidate) || std::abs(endpoint_area(candidate)) <= kEpsilon ||
          has_self_intersection(candidate) || !std::isfinite(candidate.fit_error) ||
          candidate.fit_error < 0.0 ||
          candidate.fit_error > config.maximum_fit_error ||
          !std::isfinite(candidate.complexity) || candidate.complexity < 0.0 ||
          candidate.segments.size() > config.maximum_segments_per_shape) {
        continue;
      }
      const double score = score_candidate(candidate, config);
      const auto key = std::tuple<double, std::size_t, int>{
          score, candidate.segments.size(), static_cast<int>(candidate.kind)};
      if (key < best_key) {
        best_key = key;
        best_candidate = &candidate;
      }
    }
    if (best_candidate == nullptr) {
      EngineError error = selection_error(
          ErrorCode::kNoFeasibleCandidate,
          "cycle has no candidate satisfying topology and fit gates");
      error.entity_ids.push_back(cycle.cycle_id);
      return Result<SelectedModel>::failure(std::move(error));
    }
    model.objective += std::get<0>(best_key);
    model.shapes.push_back(*best_candidate);
  }
  auto validation = validate_selected_model(model);
  if (!validation) {
    return Result<SelectedModel>::failure(validation.error());
  }
  return Result<SelectedModel>::success(std::move(model));
}

}  // namespace vectorai::binary
