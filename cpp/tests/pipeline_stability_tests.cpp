#include <cassert>
#include <cstddef>
#include <cstdint>
#include <random>
#include <string>
#include <vector>

#include "vectorai/core/binary.hpp"
#include "vectorai/core/boundary.hpp"
#include "vectorai/core/fitting.hpp"
#include "vectorai/core/model_selection.hpp"
#include "vectorai/core/region_graph.hpp"
#include "vectorai/core/svg.hpp"

namespace {

struct PipelineResult {
  vectorai::binary::TopologySummary topology;
  std::string svg;
};

PipelineResult run(const vectorai::binary::BinaryMask& mask) {
  vectorai::binary::GrayImage image;
  image.width = mask.width;
  image.height = mask.height;
  image.foreground_evidence.reserve(mask.foreground.size());
  for (const std::uint8_t value : mask.foreground) {
    image.foreground_evidence.push_back(value != 0U ? 0.98F : 0.02F);
  }
  const auto segmentation = vectorai::binary::segment(image);
  assert(segmentation);
  const auto graph = vectorai::binary::build_region_graph(segmentation.value().mask);
  assert(graph);
  const auto boundaries = vectorai::binary::estimate_boundaries(
      graph.value(), image, std::vector<float>(mask.foreground.size(), 0.9F));
  assert(boundaries);
  const auto candidates =
      vectorai::binary::generate_candidates(graph.value(), boundaries.value());
  assert(candidates);
  const auto selected =
      vectorai::binary::select_model(candidates.value(), segmentation.value().topology);
  assert(selected);
  const auto document = vectorai::binary::export_svg(
      selected.value(), vectorai::binary::SvgExportConfig{mask.width, mask.height});
  assert(document);
  assert(document.value().content.find("nan") == std::string::npos);
  assert(document.value().content.find("inf") == std::string::npos);
  return PipelineResult{segmentation.value().topology, document.value().content};
}

void test_procedural_corpus_is_stable_and_repeatable() {
  std::mt19937 generator(0xE2B1A5U);
  for (std::size_t iteration = 0U; iteration < 250U; ++iteration) {
    constexpr std::size_t width = 32U;
    constexpr std::size_t height = 28U;
    vectorai::binary::BinaryMask mask{width, height,
                                      std::vector<std::uint8_t>(width * height, 0U)};
    const std::size_t left = 2U + generator() % 6U;
    const std::size_t top = 2U + generator() % 5U;
    const std::size_t right = 22U + generator() % 8U;
    const std::size_t bottom = 19U + generator() % 7U;
    for (std::size_t y = top; y <= bottom; ++y) {
      for (std::size_t x = left; x <= right; ++x) {
        mask.foreground[y * width + x] = 1U;
      }
    }
    const bool has_hole = iteration % 2U == 0U;
    if (has_hole) {
      const std::size_t hole_left = left + 3U;
      const std::size_t hole_top = top + 3U;
      const std::size_t hole_right = right - 3U;
      const std::size_t hole_bottom = bottom - 3U;
      for (std::size_t y = hole_top; y <= hole_bottom; ++y) {
        for (std::size_t x = hole_left; x <= hole_right; ++x) {
          mask.foreground[y * width + x] = 0U;
        }
      }
    }
    const PipelineResult first = run(mask);
    const PipelineResult second = run(mask);
    assert(first.svg == second.svg);
    assert(first.topology.components == 1U);
    assert(first.topology.holes == (has_hole ? 1U : 0U));
  }
}

}  // namespace

int main() {
  test_procedural_corpus_is_stable_and_repeatable();
  return 0;
}
