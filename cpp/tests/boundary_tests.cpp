#include <cassert>
#include <cmath>
#include <vector>

#include "vectorai/core/boundary.hpp"

namespace {

using vectorai::binary::BinaryMask;
using vectorai::binary::BoundaryConfig;
using vectorai::binary::GrayImage;

void test_subpixel_vertical_edge_beats_pixel_edge() {
  BinaryMask mask{4U, 1U, {1U, 1U, 0U, 0U}};
  GrayImage image{4U, 1U, {1.0F, 1.0F, 1.0F / 3.0F, 0.0F}};
  const auto graph = vectorai::binary::build_region_graph(mask);
  assert(graph);
  const auto evidence =
      vectorai::binary::estimate_boundaries(graph.value(), image, std::vector<float>(4U, 1.0F));
  assert(evidence);

  const double truth_x = 2.25;
  bool found = false;
  for (const auto& sample : evidence.value().samples) {
    if (std::abs(sample.pixel_edge_position.x - 2.0) < 1.0e-9 &&
        std::abs(sample.tangent.y - 1.0) < 1.0e-9) {
      const double pixel_error = std::abs(sample.pixel_edge_position.x - truth_x);
      const double subpixel_error = std::abs(sample.position.x - truth_x);
      assert(subpixel_error < 1.0e-6);
      assert(subpixel_error < pixel_error);
      assert(std::abs(sample.subpixel_offset - 0.25) < 1.0e-6);
      found = true;
    }
  }
  assert(found);
}

void test_no_subpixel_ablation_stays_on_grid_edge() {
  BinaryMask mask{3U, 1U, {1U, 0U, 0U}};
  GrayImage image{3U, 1U, {1.0F, 0.25F, 0.0F}};
  const auto graph = vectorai::binary::build_region_graph(mask);
  assert(graph);
  BoundaryConfig config;
  config.enable_subpixel = false;
  const auto evidence = vectorai::binary::estimate_boundaries(graph.value(), image, {}, config);
  assert(evidence);
  for (const auto& sample : evidence.value().samples) {
    assert(sample.subpixel_offset == 0.0);
    assert(sample.position.x == sample.pixel_edge_position.x);
    assert(sample.position.y == sample.pixel_edge_position.y);
  }
}

void test_evidence_contract_and_junction_exclusion() {
  BinaryMask mask{2U, 2U, {1U, 0U, 0U, 1U}};
  GrayImage image{2U, 2U, {0.9F, 0.1F, 0.1F, 0.9F}};
  const auto graph = vectorai::binary::build_region_graph(mask);
  assert(graph);
  const auto evidence = vectorai::binary::estimate_boundaries(graph.value(), image, {});
  assert(evidence);
  assert(evidence.value().samples.size() == graph.value().canonical_edge_count);
  bool excluded = false;
  for (const auto& sample : evidence.value().samples) {
    assert(std::isfinite(sample.position.x));
    assert(std::isfinite(sample.position.y));
    assert(sample.covariance_normal > 0.0);
    assert(sample.residual >= 0.0);
    assert(sample.source_support >= 0.0);
    excluded = excluded || sample.junction_excluded;
  }
  assert(excluded);
}

void test_reliability_changes_covariance() {
  BinaryMask mask{2U, 1U, {1U, 0U}};
  GrayImage image{2U, 1U, {1.0F, 0.0F}};
  const auto graph = vectorai::binary::build_region_graph(mask);
  assert(graph);
  const auto high = vectorai::binary::estimate_boundaries(graph.value(), image, {1.0F, 1.0F});
  const auto low = vectorai::binary::estimate_boundaries(graph.value(), image, {0.0F, 0.0F});
  assert(high && low);
  assert(high.value().samples[1].covariance_normal < low.value().samples[1].covariance_normal);
}

}  // namespace

int main() {
  test_subpixel_vertical_edge_beats_pixel_edge();
  test_no_subpixel_ablation_stays_on_grid_edge();
  test_evidence_contract_and_junction_exclusion();
  test_reliability_changes_covariance();
  return 0;
}
