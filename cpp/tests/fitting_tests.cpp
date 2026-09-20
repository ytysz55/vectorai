#include <cassert>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <vector>

#include "vectorai/core/fitting.hpp"

namespace {

using vectorai::binary::BinaryMask;
using vectorai::binary::CandidateKind;
using vectorai::binary::GrayImage;
using vectorai::binary::Point2d;
using vectorai::binary::SegmentKind;

bool has_kind(const std::vector<vectorai::binary::ShapeCandidate>& candidates,
              CandidateKind kind) {
  for (const auto& candidate : candidates) {
    if (candidate.kind == kind) {
      return true;
    }
  }
  return false;
}

void test_rectangle_corner_and_primitive_recovery() {
  const std::vector<Point2d> rectangle{{1.0, 1.0}, {8.0, 1.0}, {8.0, 5.0}, {1.0, 5.0}};
  const auto corners = vectorai::binary::detect_corners(rectangle);
  const auto candidates = vectorai::binary::generate_primitive_candidates(rectangle);
  assert(corners.size() == 4U);
  assert(has_kind(candidates, CandidateKind::kPolyline));
  assert(has_kind(candidates, CandidateKind::kRectangle));
}

void test_circle_and_ellipse_classification() {
  std::vector<Point2d> circle;
  std::vector<Point2d> ellipse;
  constexpr std::size_t count = 32U;
  constexpr double pi = 3.14159265358979323846;
  for (std::size_t index = 0U; index < count; ++index) {
    const double angle = 2.0 * pi * static_cast<double>(index) / static_cast<double>(count);
    circle.push_back(Point2d{10.0 + 4.0 * std::cos(angle), 10.0 + 4.0 * std::sin(angle)});
    ellipse.push_back(Point2d{10.0 + 6.0 * std::cos(angle), 10.0 + 3.0 * std::sin(angle)});
  }
  assert(has_kind(vectorai::binary::generate_primitive_candidates(circle),
                  CandidateKind::kCircle));
  assert(has_kind(vectorai::binary::generate_primitive_candidates(ellipse),
                  CandidateKind::kEllipse));
}

void test_bezier_dp_is_closed_and_reduces_circle_segments() {
  std::vector<Point2d> circle;
  constexpr std::size_t count = 64U;
  constexpr double pi = 3.14159265358979323846;
  for (std::size_t index = 0U; index < count; ++index) {
    const double angle = 2.0 * pi * static_cast<double>(index) / static_cast<double>(count);
    circle.push_back(Point2d{5.0 * std::cos(angle), 5.0 * std::sin(angle)});
  }
  const auto result = vectorai::binary::fit_bezier_dp(circle, 0.12, 20U);
  assert(result);
  assert(result.value().segments.size() < count / 2U);
  assert(!result.value().segments.empty());
  assert(result.value().fit_error <= 0.12);
  assert(std::abs(result.value().segments.front().start.x -
                  result.value().segments.back().end.x) < 1.0e-9);
  assert(std::abs(result.value().segments.front().start.y -
                  result.value().segments.back().end.y) < 1.0e-9);
  bool has_cubic = false;
  for (const auto& segment : result.value().segments) {
    has_cubic = has_cubic || segment.kind == SegmentKind::kCubic;
  }
  assert(has_cubic);
}

void test_end_to_end_candidate_generation() {
  BinaryMask mask{8U, 6U, std::vector<std::uint8_t>(48U, 0U)};
  for (std::size_t y = 1U; y < 5U; ++y) {
    for (std::size_t x = 2U; x < 7U; ++x) {
      mask.foreground[y * mask.width + x] = 1U;
    }
  }
  GrayImage image{mask.width, mask.height, std::vector<float>(48U, 0.0F)};
  for (std::size_t index = 0U; index < mask.foreground.size(); ++index) {
    image.foreground_evidence[index] = mask.foreground[index] != 0U ? 1.0F : 0.0F;
  }
  const auto graph = vectorai::binary::build_region_graph(mask);
  assert(graph);
  const auto evidence = vectorai::binary::estimate_boundaries(graph.value(), image, {});
  assert(evidence);
  const auto candidates = vectorai::binary::generate_candidates(graph.value(), evidence.value());
  assert(candidates);
  assert(candidates.value().size() == 1U);
  assert(candidates.value()[0].corner_indices.size() == 4U);
  assert(has_kind(candidates.value()[0].candidates, CandidateKind::kRectangle));
  assert(has_kind(candidates.value()[0].candidates, CandidateKind::kBezier));
}

}  // namespace

int main() {
  test_rectangle_corner_and_primitive_recovery();
  test_circle_and_ellipse_classification();
  test_bezier_dp_is_closed_and_reduces_circle_segments();
  test_end_to_end_candidate_generation();
  return 0;
}
