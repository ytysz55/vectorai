#include <cassert>
#include <cstddef>
#include <cstdint>
#include <limits>
#include <vector>

#include "vectorai/core/binary.hpp"

namespace {

using vectorai::binary::BinaryMask;
using vectorai::binary::GrayImage;

BinaryMask make_mask(std::size_t width, std::size_t height) {
  return BinaryMask{width, height, std::vector<std::uint8_t>(width * height, 0U)};
}

void set(BinaryMask& mask, std::size_t x, std::size_t y, bool value = true) {
  mask.foreground[y * mask.width + x] = static_cast<std::uint8_t>(value);
}

void test_components_and_holes() {
  auto mask = make_mask(12U, 10U);
  for (std::size_t y = 1U; y <= 7U; ++y) {
    for (std::size_t x = 1U; x <= 7U; ++x) {
      set(mask, x, y);
    }
  }
  for (std::size_t y = 3U; y <= 5U; ++y) {
    for (std::size_t x = 3U; x <= 5U; ++x) {
      set(mask, x, y, false);
    }
  }
  set(mask, 10U, 8U);
  const auto result = vectorai::binary::analyze_topology(mask);
  assert(result);
  assert(result.value().components == 2U);
  assert(result.value().holes == 1U);
  assert(result.value().euler_characteristic() == 1);
}

void test_otsu_and_segmentation() {
  GrayImage image;
  image.width = 8U;
  image.height = 4U;
  image.foreground_evidence.resize(image.width * image.height, 0.05F);
  for (std::size_t y = 1U; y < 3U; ++y) {
    for (std::size_t x = 2U; x < 6U; ++x) {
      image.foreground_evidence[y * image.width + x] = 0.95F;
    }
  }
  const auto threshold = vectorai::binary::otsu_threshold(image);
  assert(threshold);
  assert(threshold.value() > 0.04F && threshold.value() < 0.96F);
  const auto segmentation = vectorai::binary::segment(image);
  assert(segmentation);
  assert(segmentation.value().topology.components == 1U);
  assert(segmentation.value().topology.holes == 0U);
  std::size_t foreground = 0U;
  for (const auto value : segmentation.value().mask.foreground) {
    foreground += value;
  }
  assert(foreground == 8U);
}

void test_invalid_buffers_and_nonfinite_values() {
  GrayImage invalid_size{3U, 3U, std::vector<float>(8U, 0.0F)};
  assert(!vectorai::binary::segment(invalid_size));

  GrayImage nonfinite{2U, 2U, std::vector<float>(4U, 0.0F)};
  nonfinite.foreground_evidence[2] = std::numeric_limits<float>::quiet_NaN();
  assert(!vectorai::binary::segment(nonfinite));

  auto invalid_mask = make_mask(2U, 2U);
  invalid_mask.foreground[1] = 2U;
  assert(!vectorai::binary::analyze_topology(invalid_mask));
}

void test_uniform_background_stays_empty() {
  GrayImage image{5U, 5U, std::vector<float>(25U, 0.0F)};
  const auto result = vectorai::binary::segment(image);
  assert(result);
  assert(result.value().topology.components == 0U);
  assert(result.value().topology.holes == 0U);
}

}  // namespace

int main() {
  test_components_and_holes();
  test_otsu_and_segmentation();
  test_invalid_buffers_and_nonfinite_values();
  test_uniform_background_stays_empty();
  return 0;
}
