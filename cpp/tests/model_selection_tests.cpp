#include <cassert>
#include <cstddef>
#include <cstdint>
#include <vector>

#include "vectorai/core/model_selection.hpp"

namespace {

using vectorai::binary::BinaryMask;
using vectorai::binary::CandidateKind;
using vectorai::binary::GrayImage;
using vectorai::binary::TopologySummary;

vectorai::binary::CycleCandidates rectangle_candidates() {
  vectorai::binary::CycleCandidates cycle;
  cycle.cycle_id = 0U;
  cycle.points = {{1.0, 1.0}, {7.0, 1.0}, {7.0, 5.0}, {1.0, 5.0}};
  cycle.corner_indices = vectorai::binary::detect_corners(cycle.points);
  cycle.candidates = vectorai::binary::generate_primitive_candidates(cycle.points);
  const auto bezier = vectorai::binary::fit_bezier_dp(cycle.points);
  assert(bezier);
  cycle.candidates.push_back(bezier.value());
  return cycle;
}

void test_prefers_exact_low_complexity_rectangle() {
  const auto selected =
      vectorai::binary::select_model({rectangle_candidates()}, TopologySummary{1U, 0U});
  assert(selected);
  assert(selected.value().shapes.size() == 1U);
  assert(selected.value().shapes[0].kind == CandidateKind::kRectangle);
  assert(vectorai::binary::validate_selected_model(selected.value()));
}

void test_topology_mismatch_is_a_hard_failure() {
  const auto selected =
      vectorai::binary::select_model({rectangle_candidates()}, TopologySummary{1U, 1U});
  assert(!selected);
  assert(selected.error().code == vectorai::ErrorCode::kTopologyAmbiguous);
}

void test_fit_gate_can_reject_all_candidates() {
  auto cycle = rectangle_candidates();
  for (auto& candidate : cycle.candidates) {
    candidate.fit_error = 10.0;
  }
  const auto selected = vectorai::binary::select_model({cycle}, TopologySummary{1U, 0U});
  assert(!selected);
  assert(selected.error().code == vectorai::ErrorCode::kNoFeasibleCandidate);
}

void test_ring_pipeline_preserves_two_cycles() {
  BinaryMask mask{9U, 9U, std::vector<std::uint8_t>(81U, 0U)};
  for (std::size_t y = 1U; y < 8U; ++y) {
    for (std::size_t x = 1U; x < 8U; ++x) {
      mask.foreground[y * mask.width + x] = 1U;
    }
  }
  for (std::size_t y = 3U; y < 6U; ++y) {
    for (std::size_t x = 3U; x < 6U; ++x) {
      mask.foreground[y * mask.width + x] = 0U;
    }
  }
  GrayImage image{mask.width, mask.height, std::vector<float>(81U, 0.0F)};
  for (std::size_t index = 0U; index < mask.foreground.size(); ++index) {
    image.foreground_evidence[index] = mask.foreground[index] != 0U ? 1.0F : 0.0F;
  }
  const auto graph = vectorai::binary::build_region_graph(mask);
  assert(graph);
  const auto evidence = vectorai::binary::estimate_boundaries(graph.value(), image, {});
  assert(evidence);
  const auto candidates = vectorai::binary::generate_candidates(graph.value(), evidence.value());
  assert(candidates);
  const auto topology = vectorai::binary::analyze_topology(mask);
  assert(topology);
  const auto selected = vectorai::binary::select_model(candidates.value(), topology.value());
  assert(selected);
  assert(selected.value().shapes.size() == 2U);
  assert(selected.value().topology.components == 1U);
  assert(selected.value().topology.holes == 1U);
}

void test_self_intersection_is_a_hard_failure() {
  const std::vector<vectorai::binary::Point2d> points{
      {0.0, 0.0}, {4.0, 4.0}, {0.0, 5.0}, {5.0, 1.0}};
  vectorai::binary::ShapeCandidate crossing;
  crossing.kind = CandidateKind::kPolyline;
  crossing.complexity = 4.0;
  for (std::size_t index = 0U; index < points.size(); ++index) {
    const auto start = points[index];
    const auto end = points[(index + 1U) % points.size()];
    crossing.segments.push_back(
        {vectorai::binary::SegmentKind::kLine, start, start, end, end});
  }
  const vectorai::binary::SelectedModel invalid{{1U, 0U}, {crossing}, 0.0};
  assert(!vectorai::binary::validate_selected_model(invalid));

  vectorai::binary::CycleCandidates cycle;
  cycle.cycle_id = 9U;
  cycle.points = points;
  cycle.candidates = {crossing};
  const auto selected = vectorai::binary::select_model({cycle}, TopologySummary{1U, 0U});
  assert(!selected);
  assert(selected.error().code == vectorai::ErrorCode::kNoFeasibleCandidate);
}

void test_selection_is_deterministic() {
  const auto cycle = rectangle_candidates();
  const auto first = vectorai::binary::select_model({cycle}, TopologySummary{1U, 0U});
  const auto second = vectorai::binary::select_model({cycle}, TopologySummary{1U, 0U});
  assert(first && second);
  assert(first.value().objective == second.value().objective);
  assert(first.value().shapes[0].kind == second.value().shapes[0].kind);
  assert(first.value().shapes[0].segments.size() == second.value().shapes[0].segments.size());
}

}  // namespace

int main() {
  test_prefers_exact_low_complexity_rectangle();
  test_topology_mismatch_is_a_hard_failure();
  test_fit_gate_can_reject_all_candidates();
  test_ring_pipeline_preserves_two_cycles();
  test_self_intersection_is_a_hard_failure();
  test_selection_is_deterministic();
  return 0;
}
