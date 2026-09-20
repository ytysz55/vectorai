#include "vectorai/core/binary.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <limits>
#include <queue>
#include <string>
#include <utility>
#include <vector>

namespace vectorai::binary {
namespace {

[[nodiscard]] EngineError make_error(ErrorCode code, Stage stage, std::string message) {
  EngineError error;
  error.code = code;
  error.stage = stage;
  error.message = std::move(message);
  return error;
}

[[nodiscard]] Result<void> validate_dimensions(std::size_t width, std::size_t height,
                                               std::size_t value_count, Stage stage) {
  if (width == 0U || height == 0U || width > kMaxPixels || height > kMaxPixels ||
      width > kMaxPixels / height || width * height > kMaxPixels) {
    return Result<void>::failure(
        make_error(ErrorCode::kResourceLimit, stage, "image dimensions exceed binary limits"));
  }
  if (value_count != width * height) {
    return Result<void>::failure(make_error(ErrorCode::kInternalInvariantViolation, stage,
                                            "image buffer size does not match dimensions"));
  }
  return Result<void>::success();
}

[[nodiscard]] std::vector<std::size_t> neighbors(std::size_t index, std::size_t width,
                                                 std::size_t height) {
  const std::size_t x = index % width;
  const std::size_t y = index / width;
  std::vector<std::size_t> result;
  result.reserve(4U);
  if (x > 0U) {
    result.push_back(index - 1U);
  }
  if (x + 1U < width) {
    result.push_back(index + 1U);
  }
  if (y > 0U) {
    result.push_back(index - width);
  }
  if (y + 1U < height) {
    result.push_back(index + width);
  }
  return result;
}

struct ComponentCounts {
  std::size_t components{0};
  std::size_t enclosed{0};
};

[[nodiscard]] ComponentCounts count_components(const BinaryMask& mask, bool target) {
  std::vector<std::uint8_t> visited(mask.foreground.size(), 0U);
  ComponentCounts counts;
  for (std::size_t start = 0; start < mask.foreground.size(); ++start) {
    if (visited[start] != 0U || mask.foreground[start] != static_cast<std::uint8_t>(target)) {
      continue;
    }
    ++counts.components;
    bool touches_border = false;
    std::queue<std::size_t> pending;
    pending.push(start);
    visited[start] = 1U;
    while (!pending.empty()) {
      const std::size_t current = pending.front();
      pending.pop();
      const std::size_t x = current % mask.width;
      const std::size_t y = current / mask.width;
      touches_border = touches_border || x == 0U || y == 0U || x + 1U == mask.width ||
                       y + 1U == mask.height;
      for (const std::size_t adjacent : neighbors(current, mask.width, mask.height)) {
        if (visited[adjacent] == 0U &&
            mask.foreground[adjacent] == static_cast<std::uint8_t>(target)) {
          visited[adjacent] = 1U;
          pending.push(adjacent);
        }
      }
    }
    if (!touches_border) {
      ++counts.enclosed;
    }
  }
  return counts;
}

}  // namespace

Result<float> otsu_threshold(const GrayImage& image) {
  const auto dimensions =
      validate_dimensions(image.width, image.height, image.foreground_evidence.size(),
                          Stage::kSegmentation);
  if (!dimensions) {
    return Result<float>::failure(dimensions.error());
  }

  std::array<std::uint64_t, 256U> histogram{};
  float minimum = 1.0F;
  float maximum = 0.0F;
  for (const float value : image.foreground_evidence) {
    if (!std::isfinite(value) || value < 0.0F || value > 1.0F) {
      return Result<float>::failure(make_error(ErrorCode::kInternalInvariantViolation,
                                               Stage::kSegmentation,
                                               "foreground evidence must be finite in [0, 1]"));
    }
    minimum = std::min(minimum, value);
    maximum = std::max(maximum, value);
    const auto bucket = static_cast<std::size_t>(
        std::clamp(std::lround(static_cast<double>(value) * 255.0), 0L, 255L));
    ++histogram[bucket];
  }
  if (maximum - minimum <= std::numeric_limits<float>::epsilon()) {
    return Result<float>::success(maximum < 0.5F ? 1.0F : 0.0F);
  }

  const std::uint64_t total = static_cast<std::uint64_t>(image.foreground_evidence.size());
  double weighted_total = 0.0;
  for (std::size_t index = 0; index < histogram.size(); ++index) {
    weighted_total += static_cast<double>(index) * static_cast<double>(histogram[index]);
  }

  std::uint64_t background_weight = 0U;
  double background_sum = 0.0;
  double best_variance = -1.0;
  std::size_t best_bucket = 127U;
  for (std::size_t index = 0; index + 1U < histogram.size(); ++index) {
    background_weight += histogram[index];
    if (background_weight == 0U) {
      continue;
    }
    const std::uint64_t foreground_weight = total - background_weight;
    if (foreground_weight == 0U) {
      break;
    }
    background_sum += static_cast<double>(index) * static_cast<double>(histogram[index]);
    const double background_mean = background_sum / static_cast<double>(background_weight);
    const double foreground_mean =
        (weighted_total - background_sum) / static_cast<double>(foreground_weight);
    const double difference = background_mean - foreground_mean;
    const double variance = static_cast<double>(background_weight) *
                            static_cast<double>(foreground_weight) * difference * difference;
    if (variance > best_variance) {
      best_variance = variance;
      best_bucket = index;
    }
  }
  const float threshold = static_cast<float>((static_cast<double>(best_bucket) + 0.5) / 255.0);
  return Result<float>::success(threshold);
}

Result<TopologySummary> analyze_topology(const BinaryMask& mask) {
  const auto dimensions =
      validate_dimensions(mask.width, mask.height, mask.foreground.size(), Stage::kTopology);
  if (!dimensions) {
    return Result<TopologySummary>::failure(dimensions.error());
  }
  if (std::any_of(mask.foreground.begin(), mask.foreground.end(),
                  [](std::uint8_t value) { return value > 1U; })) {
    return Result<TopologySummary>::failure(make_error(
        ErrorCode::kInternalInvariantViolation, Stage::kTopology, "binary mask contains non-binary value"));
  }
  const ComponentCounts foreground = count_components(mask, true);
  const ComponentCounts background = count_components(mask, false);
  TopologySummary topology;
  topology.components = foreground.components;
  topology.holes = background.enclosed;
  return Result<TopologySummary>::success(topology);
}

Result<SegmentationResult> segment(const GrayImage& image, float threshold) {
  const auto dimensions =
      validate_dimensions(image.width, image.height, image.foreground_evidence.size(),
                          Stage::kSegmentation);
  if (!dimensions) {
    return Result<SegmentationResult>::failure(dimensions.error());
  }

  float selected_threshold = threshold;
  if (threshold < 0.0F) {
    auto automatic = otsu_threshold(image);
    if (!automatic) {
      return Result<SegmentationResult>::failure(automatic.error());
    }
    selected_threshold = automatic.value();
  }
  if (!std::isfinite(selected_threshold) || selected_threshold < 0.0F ||
      selected_threshold > 1.0F) {
    return Result<SegmentationResult>::failure(make_error(
        ErrorCode::kTopologyAmbiguous, Stage::kSegmentation, "segmentation threshold must be in [0, 1]"));
  }

  BinaryMask mask;
  mask.width = image.width;
  mask.height = image.height;
  mask.foreground.resize(image.foreground_evidence.size(), 0U);
  for (std::size_t index = 0; index < image.foreground_evidence.size(); ++index) {
    const float value = image.foreground_evidence[index];
    if (!std::isfinite(value) || value < 0.0F || value > 1.0F) {
      return Result<SegmentationResult>::failure(make_error(
          ErrorCode::kInternalInvariantViolation, Stage::kSegmentation,
          "foreground evidence must be finite in [0, 1]"));
    }
    mask.foreground[index] = static_cast<std::uint8_t>(value >= selected_threshold);
  }
  auto topology = analyze_topology(mask);
  if (!topology) {
    return Result<SegmentationResult>::failure(topology.error());
  }
  SegmentationResult result;
  result.mask = std::move(mask);
  result.topology = topology.value();
  result.threshold = selected_threshold;
  return Result<SegmentationResult>::success(std::move(result));
}

}  // namespace vectorai::binary
