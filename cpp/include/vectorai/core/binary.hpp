#pragma once

#include <cstddef>
#include <cstdint>
#include <vector>

#include "vectorai/core/result.hpp"

namespace vectorai::binary {

inline constexpr std::size_t kMaxPixels = 16'777'216;

struct GrayImage {
  std::size_t width{0};
  std::size_t height{0};
  std::vector<float> foreground_evidence;

  [[nodiscard]] float at(std::size_t x, std::size_t y) const noexcept {
    return foreground_evidence[y * width + x];
  }
};

struct BinaryMask {
  std::size_t width{0};
  std::size_t height{0};
  std::vector<std::uint8_t> foreground;

  [[nodiscard]] bool at(std::size_t x, std::size_t y) const noexcept {
    return foreground[y * width + x] != 0U;
  }
};

struct TopologySummary {
  std::size_t components{0};
  std::size_t holes{0};

  [[nodiscard]] std::int64_t euler_characteristic() const noexcept {
    return static_cast<std::int64_t>(components) - static_cast<std::int64_t>(holes);
  }
};

struct SegmentationResult {
  BinaryMask mask;
  TopologySummary topology;
  float threshold{0.5F};
};

[[nodiscard]] Result<float> otsu_threshold(const GrayImage& image);
[[nodiscard]] Result<TopologySummary> analyze_topology(const BinaryMask& mask);
[[nodiscard]] Result<SegmentationResult> segment(const GrayImage& image,
                                                 float threshold = -1.0F);

}  // namespace vectorai::binary
