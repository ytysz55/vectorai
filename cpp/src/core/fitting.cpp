#include "vectorai/core/fitting.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <limits>
#include <map>
#include <string>
#include <utility>
#include <vector>

namespace vectorai::binary {
namespace {

constexpr double kPi = 3.14159265358979323846;
constexpr double kEpsilon = 1.0e-9;

[[nodiscard]] EngineError fitting_error(ErrorCode code, std::string message) {
  EngineError error;
  error.code = code;
  error.stage = Stage::kCandidateGeneration;
  error.message = std::move(message);
  return error;
}

[[nodiscard]] Point2d add(Point2d left, Point2d right) {
  return Point2d{left.x + right.x, left.y + right.y};
}

[[nodiscard]] Point2d subtract(Point2d left, Point2d right) {
  return Point2d{left.x - right.x, left.y - right.y};
}

[[nodiscard]] Point2d scale(Point2d point, double factor) {
  return Point2d{point.x * factor, point.y * factor};
}

[[nodiscard]] double dot(Point2d left, Point2d right) {
  return left.x * right.x + left.y * right.y;
}

[[nodiscard]] double cross(Point2d left, Point2d right) {
  return left.x * right.y - left.y * right.x;
}

[[nodiscard]] double length(Point2d value) {
  return std::sqrt(dot(value, value));
}

[[nodiscard]] double distance(Point2d left, Point2d right) {
  return length(subtract(left, right));
}

[[nodiscard]] Point2d normalized(Point2d value) {
  const double magnitude = length(value);
  return magnitude <= kEpsilon ? Point2d{} : scale(value, 1.0 / magnitude);
}

[[nodiscard]] bool equal(Point2d left, Point2d right) {
  return distance(left, right) <= kEpsilon;
}

[[nodiscard]] std::vector<Point2d> unique_closed_points(const std::vector<Point2d>& input) {
  std::vector<Point2d> points;
  points.reserve(input.size());
  for (const Point2d point : input) {
    if (points.empty() || !equal(points.back(), point)) {
      points.push_back(point);
    }
  }
  if (points.size() > 1U && equal(points.front(), points.back())) {
    points.pop_back();
  }
  bool changed = true;
  while (changed && points.size() > 3U) {
    changed = false;
    std::vector<Point2d> simplified;
    simplified.reserve(points.size());
    for (std::size_t index = 0U; index < points.size(); ++index) {
      const Point2d previous = points[(index + points.size() - 1U) % points.size()];
      const Point2d current = points[index];
      const Point2d next = points[(index + 1U) % points.size()];
      const Point2d incoming = subtract(current, previous);
      const Point2d outgoing = subtract(next, current);
      if (std::abs(cross(incoming, outgoing)) <= kEpsilon && dot(incoming, outgoing) > 0.0) {
        changed = true;
      } else {
        simplified.push_back(current);
      }
    }
    points = std::move(simplified);
  }
  return points;
}

[[nodiscard]] VectorSegment line_segment(Point2d start, Point2d end) {
  return VectorSegment{SegmentKind::kLine, start, start, end, end};
}

[[nodiscard]] VectorSegment cubic_segment(Point2d start, Point2d control1,
                                           Point2d control2, Point2d end) {
  return VectorSegment{SegmentKind::kCubic, start, control1, control2, end};
}

[[nodiscard]] ShapeCandidate polyline_candidate(const std::vector<Point2d>& points) {
  ShapeCandidate candidate;
  candidate.kind = CandidateKind::kPolyline;
  candidate.complexity = static_cast<double>(points.size());
  for (std::size_t index = 0U; index < points.size(); ++index) {
    candidate.segments.push_back(line_segment(points[index], points[(index + 1U) % points.size()]));
  }
  return candidate;
}

[[nodiscard]] Point2d cubic_at(const VectorSegment& segment, double parameter) {
  const double inverse = 1.0 - parameter;
  return add(add(scale(segment.start, inverse * inverse * inverse),
                 scale(segment.control1, 3.0 * inverse * inverse * parameter)),
             add(scale(segment.control2, 3.0 * inverse * parameter * parameter),
                 scale(segment.end, parameter * parameter * parameter)));
}

[[nodiscard]] double point_line_distance(Point2d point, Point2d start, Point2d end) {
  const Point2d chord = subtract(end, start);
  const double squared = dot(chord, chord);
  if (squared <= kEpsilon) {
    return distance(point, start);
  }
  const double parameter = std::clamp(dot(subtract(point, start), chord) / squared, 0.0, 1.0);
  return distance(point, add(start, scale(chord, parameter)));
}

struct IntervalFit {
  VectorSegment segment;
  double error{std::numeric_limits<double>::infinity()};
  double cost{std::numeric_limits<double>::infinity()};
};

[[nodiscard]] IntervalFit fit_interval(const std::vector<Point2d>& points, std::size_t first,
                                       std::size_t last, bool cubic) {
  const Point2d start = points[first];
  const Point2d end = points[last];
  VectorSegment segment = line_segment(start, end);
  if (cubic) {
    const Point2d start_tangent = normalized(subtract(points[first + 1U], points[first]));
    const Point2d end_tangent = normalized(subtract(points[last], points[last - 1U]));
    const double chord = distance(start, end);
    segment = cubic_segment(start, add(start, scale(start_tangent, chord / 3.0)),
                            subtract(end, scale(end_tangent, chord / 3.0)), end);
  }

  std::vector<double> cumulative(last - first + 1U, 0.0);
  for (std::size_t index = first + 1U; index <= last; ++index) {
    cumulative[index - first] =
        cumulative[index - first - 1U] + distance(points[index - 1U], points[index]);
  }
  const double total = cumulative.back();
  double maximum_error = 0.0;
  for (std::size_t index = first + 1U; index < last; ++index) {
    const double parameter = total <= kEpsilon ? 0.0 : cumulative[index - first] / total;
    const double error = cubic ? distance(points[index], cubic_at(segment, parameter))
                               : point_line_distance(points[index], start, end);
    maximum_error = std::max(maximum_error, error);
  }
  const double complexity = cubic ? 2.0 : 1.0;
  return IntervalFit{segment, maximum_error, complexity + maximum_error * 0.05};
}

[[nodiscard]] std::vector<VectorSegment> ellipse_segments(Point2d center, double radius_x,
                                                           double radius_y) {
  constexpr double kappa = 0.5522847498307936;
  const Point2d right{center.x + radius_x, center.y};
  const Point2d bottom{center.x, center.y + radius_y};
  const Point2d left{center.x - radius_x, center.y};
  const Point2d top{center.x, center.y - radius_y};
  return {
      cubic_segment(right, Point2d{right.x, right.y + kappa * radius_y},
                    Point2d{bottom.x + kappa * radius_x, bottom.y}, bottom),
      cubic_segment(bottom, Point2d{bottom.x - kappa * radius_x, bottom.y},
                    Point2d{left.x, left.y + kappa * radius_y}, left),
      cubic_segment(left, Point2d{left.x, left.y - kappa * radius_y},
                    Point2d{top.x - kappa * radius_x, top.y}, top),
      cubic_segment(top, Point2d{top.x + kappa * radius_x, top.y},
                    Point2d{right.x, right.y - kappa * radius_y}, right),
  };
}

[[nodiscard]] std::array<double, 4U> bounds(const std::vector<Point2d>& points) {
  std::array<double, 4U> result{points.front().x, points.front().y, points.front().x,
                                points.front().y};
  for (const Point2d point : points) {
    result[0] = std::min(result[0], point.x);
    result[1] = std::min(result[1], point.y);
    result[2] = std::max(result[2], point.x);
    result[3] = std::max(result[3], point.y);
  }
  return result;
}

[[nodiscard]] bool rectangle_geometry(const std::vector<Point2d>& points) {
  if (points.size() != 4U) {
    return false;
  }
  for (std::size_t index = 0U; index < 4U; ++index) {
    const Point2d incoming = normalized(subtract(points[index], points[(index + 3U) % 4U]));
    const Point2d outgoing = normalized(subtract(points[(index + 1U) % 4U], points[index]));
    if (std::abs(dot(incoming, outgoing)) > 0.05) {
      return false;
    }
  }
  return true;
}

[[nodiscard]] std::vector<Point2d> adjusted_cycle_points(
    const RegionGraph& graph, const std::vector<std::uint64_t>& cycle,
    const std::map<std::uint64_t, BoundarySample>& samples) {
  std::vector<Point2d> points;
  points.reserve(cycle.size());
  for (std::size_t index = 0U; index < cycle.size(); ++index) {
    const HalfEdge& current = graph.half_edges[cycle[index]];
    const HalfEdge& previous = graph.half_edges[cycle[(index + cycle.size() - 1U) % cycle.size()]];
    const GridPoint vertex = graph.vertices[current.origin].position;
    const BoundarySample& current_sample = samples.at(current.canonical_edge);
    const BoundarySample& previous_sample = samples.at(previous.canonical_edge);
    const Point2d current_shift = scale(current_sample.outward_normal, current_sample.subpixel_offset);
    const Point2d previous_shift =
        scale(previous_sample.outward_normal, previous_sample.subpixel_offset);
    points.push_back(Point2d{static_cast<double>(vertex.x) +
                                 0.5 * (current_shift.x + previous_shift.x),
                             static_cast<double>(vertex.y) +
                                 0.5 * (current_shift.y + previous_shift.y)});
  }
  return unique_closed_points(points);
}

}  // namespace

std::vector<std::size_t> detect_corners(const std::vector<Point2d>& closed_points,
                                        double angle_degrees) {
  const std::vector<Point2d> points = unique_closed_points(closed_points);
  std::vector<std::size_t> corners;
  if (points.size() < 3U || !std::isfinite(angle_degrees) || angle_degrees <= 0.0 ||
      angle_degrees >= 180.0) {
    return corners;
  }
  const double threshold = angle_degrees * kPi / 180.0;
  const std::size_t span = std::max<std::size_t>(1U, points.size() / 32U);
  for (std::size_t index = 0U; index < points.size(); ++index) {
    const Point2d incoming = normalized(subtract(
        points[index], points[(index + points.size() - span) % points.size()]));
    const Point2d outgoing = normalized(
        subtract(points[(index + span) % points.size()], points[index]));
    const double turning = std::acos(std::clamp(dot(incoming, outgoing), -1.0, 1.0));
    if (turning >= threshold) {
      corners.push_back(index);
    }
  }
  return corners;
}

std::vector<ShapeCandidate> generate_primitive_candidates(
    const std::vector<Point2d>& closed_points, double tolerance) {
  const std::vector<Point2d> points = unique_closed_points(closed_points);
  std::vector<ShapeCandidate> candidates;
  if (points.size() < 3U || !std::isfinite(tolerance) || tolerance < 0.0) {
    return candidates;
  }
  candidates.push_back(polyline_candidate(points));
  if (rectangle_geometry(points)) {
    ShapeCandidate rectangle = polyline_candidate(points);
    rectangle.kind = CandidateKind::kRectangle;
    rectangle.complexity = 1.0;
    candidates.push_back(std::move(rectangle));
  }
  if (points.size() >= 8U) {
    const auto extent = bounds(points);
    const Point2d center{0.5 * (extent[0] + extent[2]), 0.5 * (extent[1] + extent[3])};
    const double radius_x = 0.5 * (extent[2] - extent[0]);
    const double radius_y = 0.5 * (extent[3] - extent[1]);
    if (radius_x > kEpsilon && radius_y > kEpsilon) {
      double squared_error = 0.0;
      for (const Point2d point : points) {
        const double nx = (point.x - center.x) / radius_x;
        const double ny = (point.y - center.y) / radius_y;
        const double radial_error =
            std::abs(std::sqrt(nx * nx + ny * ny) - 1.0) * std::max(radius_x, radius_y);
        squared_error += radial_error * radial_error;
      }
      const double root_mean_square = std::sqrt(squared_error / static_cast<double>(points.size()));
      const double ellipse_gate = std::max(0.05, std::min(0.75, tolerance));
      const auto significant_corners = detect_corners(points, 45.0);
      if (root_mean_square <= ellipse_gate && significant_corners.size() <= 2U) {
        ShapeCandidate ellipse;
        ellipse.kind = std::abs(radius_x - radius_y) / std::max(radius_x, radius_y) <= 0.12
                           ? CandidateKind::kCircle
                           : CandidateKind::kEllipse;
        ellipse.segments = ellipse_segments(center, radius_x, radius_y);
        ellipse.fit_error = root_mean_square;
        ellipse.complexity = 1.0;
        candidates.push_back(std::move(ellipse));
      }
    }
  }
  if (points.size() >= 8U && points.size() <= 20U &&
      detect_corners(points, 45.0).size() == 4U) {
    const auto extent = bounds(points);
    const double width = extent[2] - extent[0];
    const double height = extent[3] - extent[1];
    const double radius = std::min(width, height) * 0.2;
    if (radius > kEpsilon) {
      ShapeCandidate rounded;
      rounded.kind = CandidateKind::kRoundedRectangle;
      rounded.fit_error = tolerance;
      rounded.complexity = 2.0;
      const Point2d top_left{extent[0] + radius, extent[1]};
      const Point2d top_right{extent[2] - radius, extent[1]};
      const Point2d right_top{extent[2], extent[1] + radius};
      const Point2d right_bottom{extent[2], extent[3] - radius};
      const Point2d bottom_right{extent[2] - radius, extent[3]};
      const Point2d bottom_left{extent[0] + radius, extent[3]};
      const Point2d left_bottom{extent[0], extent[3] - radius};
      const Point2d left_top{extent[0], extent[1] + radius};
      rounded.segments = {line_segment(top_left, top_right),
                          cubic_segment(top_right, top_right, right_top, right_top),
                          line_segment(right_top, right_bottom),
                          cubic_segment(right_bottom, right_bottom, bottom_right, bottom_right),
                          line_segment(bottom_right, bottom_left),
                          cubic_segment(bottom_left, bottom_left, left_bottom, left_bottom),
                          line_segment(left_bottom, left_top),
                          cubic_segment(left_top, left_top, top_left, top_left)};
      candidates.push_back(std::move(rounded));
    }
  }
  return candidates;
}

Result<ShapeCandidate> fit_bezier_dp(const std::vector<Point2d>& closed_points,
                                     double tolerance, std::size_t maximum_curve_span) {
  std::vector<Point2d> points = unique_closed_points(closed_points);
  if (points.size() < 3U || points.size() > 4096U || !std::isfinite(tolerance) ||
      tolerance < 0.0 || maximum_curve_span < 2U) {
    return Result<ShapeCandidate>::failure(fitting_error(
        ErrorCode::kNoFeasibleCandidate, "Bezier DP input or resource bound is invalid"));
  }
  points.push_back(points.front());
  const std::size_t count = points.size();
  std::vector<double> best(count, std::numeric_limits<double>::infinity());
  std::vector<double> chosen_error(count, 0.0);
  std::vector<std::size_t> predecessor(count, 0U);
  std::vector<VectorSegment> chosen(count);
  best[0] = 0.0;
  for (std::size_t last = 1U; last < count; ++last) {
    const std::size_t first_min = last > maximum_curve_span ? last - maximum_curve_span : 0U;
    for (std::size_t first = first_min; first < last; ++first) {
      if (!std::isfinite(best[first])) {
        continue;
      }
      const bool try_cubic = last > first + 1U;
      const IntervalFit line = fit_interval(points, first, last, false);
      if (line.error <= tolerance && best[first] + line.cost < best[last]) {
        best[last] = best[first] + line.cost;
        predecessor[last] = first;
        chosen[last] = line.segment;
        chosen_error[last] = line.error;
      }
      if (try_cubic) {
        const IntervalFit cubic = fit_interval(points, first, last, true);
        if (cubic.error <= tolerance && best[first] + cubic.cost < best[last]) {
          best[last] = best[first] + cubic.cost;
          predecessor[last] = first;
          chosen[last] = cubic.segment;
          chosen_error[last] = cubic.error;
        }
      }
    }
  }
  if (!std::isfinite(best.back())) {
    return Result<ShapeCandidate>::failure(
        fitting_error(ErrorCode::kNoFeasibleCandidate, "Bezier DP found no closed fit"));
  }
  ShapeCandidate candidate;
  candidate.kind = CandidateKind::kBezier;
  candidate.complexity = best.back();
  std::size_t current = count - 1U;
  while (current > 0U) {
    candidate.segments.push_back(chosen[current]);
    candidate.fit_error = std::max(candidate.fit_error, chosen_error[current]);
    current = predecessor[current];
  }
  std::reverse(candidate.segments.begin(), candidate.segments.end());
  return Result<ShapeCandidate>::success(std::move(candidate));
}

Result<std::vector<CycleCandidates>> generate_candidates(const RegionGraph& graph,
                                                          const BoundaryEvidence& evidence,
                                                          const FittingConfig& config) {
  if (evidence.samples.size() != graph.canonical_edge_count ||
      !std::isfinite(config.corner_angle_degrees) ||
      !std::isfinite(config.primitive_tolerance) ||
      !std::isfinite(config.bezier_tolerance)) {
    return Result<std::vector<CycleCandidates>>::failure(fitting_error(
        ErrorCode::kInsufficientBoundaryEvidence, "candidate input does not match region graph"));
  }
  std::map<std::uint64_t, BoundarySample> samples;
  for (const BoundarySample& sample : evidence.samples) {
    samples.emplace(sample.canonical_edge, sample);
  }
  if (samples.size() != evidence.samples.size()) {
    return Result<std::vector<CycleCandidates>>::failure(fitting_error(
        ErrorCode::kInsufficientBoundaryEvidence, "boundary evidence has duplicate edge IDs"));
  }
  const auto cycles = extract_face_cycles(graph, 1U);
  if (!cycles) {
    return Result<std::vector<CycleCandidates>>::failure(cycles.error());
  }
  std::vector<CycleCandidates> result;
  result.reserve(cycles.value().size());
  for (std::size_t index = 0U; index < cycles.value().size(); ++index) {
    CycleCandidates cycle;
    cycle.cycle_id = static_cast<std::uint64_t>(index);
    cycle.points = adjusted_cycle_points(graph, cycles.value()[index], samples);
    if (cycle.points.size() < 3U) {
      return Result<std::vector<CycleCandidates>>::failure(fitting_error(
          ErrorCode::kNoFeasibleCandidate, "boundary cycle collapsed below three vertices"));
    }
    cycle.corner_indices = detect_corners(cycle.points, config.corner_angle_degrees);
    cycle.candidates =
        generate_primitive_candidates(cycle.points, config.primitive_tolerance);
    auto bezier = fit_bezier_dp(cycle.points, config.bezier_tolerance,
                                config.maximum_curve_span);
    if (bezier) {
      cycle.candidates.push_back(std::move(bezier.value()));
    }
    if (cycle.candidates.empty()) {
      return Result<std::vector<CycleCandidates>>::failure(fitting_error(
          ErrorCode::kNoFeasibleCandidate, "boundary cycle produced no candidates"));
    }
    result.push_back(std::move(cycle));
  }
  return Result<std::vector<CycleCandidates>>::success(std::move(result));
}

}  // namespace vectorai::binary
