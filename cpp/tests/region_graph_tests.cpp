#include <cassert>
#include <cstddef>
#include <cstdint>
#include <random>
#include <vector>

#include "vectorai/core/region_graph.hpp"

namespace {

using vectorai::binary::BinaryMask;

BinaryMask mask(std::size_t width, std::size_t height) {
  return BinaryMask{width, height, std::vector<std::uint8_t>(width * height, 0U)};
}

void set(BinaryMask& value, std::size_t x, std::size_t y, bool foreground = true) {
  value.foreground[y * value.width + x] = static_cast<std::uint8_t>(foreground);
}

void test_single_pixel_graph() {
  auto input = mask(3U, 3U);
  set(input, 1U, 1U);
  const auto result = vectorai::binary::build_region_graph(input);
  assert(result);
  const auto& graph = result.value();
  assert(graph.vertices.size() == 4U);
  assert(graph.canonical_edge_count == 4U);
  assert(graph.half_edges.size() == 8U);
  assert(graph.faces[1].boundary_cycles.size() == 1U);
  assert(graph.faces[0].boundary_cycles.size() == 1U);
  assert(vectorai::binary::validate_region_graph(graph));

  const auto foreground_cycles = vectorai::binary::extract_face_cycles(graph, 1U);
  assert(foreground_cycles);
  assert(foreground_cycles.value().size() == 1U);
  assert(foreground_cycles.value()[0].size() == 4U);
}

void test_ring_has_outer_and_hole_cycles() {
  auto input = mask(7U, 7U);
  for (std::size_t y = 1U; y < 6U; ++y) {
    for (std::size_t x = 1U; x < 6U; ++x) {
      set(input, x, y);
    }
  }
  for (std::size_t y = 2U; y < 5U; ++y) {
    for (std::size_t x = 2U; x < 5U; ++x) {
      set(input, x, y, false);
    }
  }
  const auto result = vectorai::binary::build_region_graph(input);
  assert(result);
  assert(result.value().faces[1].boundary_cycles.size() == 2U);
  assert(result.value().faces[0].boundary_cycles.size() == 2U);
  assert(vectorai::binary::validate_region_graph(result.value()));
}

void test_twins_share_canonical_geometry() {
  auto input = mask(4U, 3U);
  set(input, 1U, 1U);
  set(input, 2U, 1U);
  const auto result = vectorai::binary::build_region_graph(input);
  assert(result);
  const auto& graph = result.value();
  for (const auto& edge : graph.half_edges) {
    const auto& twin = graph.half_edges[edge.twin];
    assert(edge.canonical_edge == twin.canonical_edge);
    assert(edge.origin == twin.target);
    assert(edge.target == twin.origin);
  }
}

void test_random_small_masks_preserve_invariants() {
  std::mt19937 generator(0x5EEDU);
  std::bernoulli_distribution foreground(0.43);
  for (std::size_t iteration = 0U; iteration < 1000U; ++iteration) {
    const std::size_t width = 1U + generator() % 8U;
    const std::size_t height = 1U + generator() % 8U;
    auto input = mask(width, height);
    for (auto& value : input.foreground) {
      value = static_cast<std::uint8_t>(foreground(generator));
    }
    const auto result = vectorai::binary::build_region_graph(input);
    assert(result);
    assert(vectorai::binary::validate_region_graph(result.value()));
  }
}

void test_validator_rejects_broken_twin() {
  auto input = mask(2U, 2U);
  set(input, 0U, 0U);
  auto result = vectorai::binary::build_region_graph(input);
  assert(result);
  result.value().half_edges[0].twin = 0U;
  assert(!vectorai::binary::validate_region_graph(result.value()));
}

}  // namespace

int main() {
  test_single_pixel_graph();
  test_ring_has_outer_and_hole_cycles();
  test_twins_share_canonical_geometry();
  test_random_small_masks_preserve_invariants();
  test_validator_rejects_broken_twin();
  return 0;
}
