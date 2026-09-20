#pragma once

#include <cstddef>
#include <cstdint>
#include <vector>

#include "vectorai/core/binary.hpp"
#include "vectorai/core/region_graph.hpp"
#include "vectorai/core/result.hpp"

namespace vectorai::binary {

struct Point2d {
  double x{0.0};
  double y{0.0};
};

struct BoundaryConfig {
  float threshold{0.5F};
  float minimum_contrast{0.02F};
  bool enable_subpixel{true};
};

struct BoundarySample {
  std::uint64_t canonical_edge{0};
  Point2d position;
  Point2d pixel_edge_position;
  Point2d tangent;
  Point2d outward_normal;
  double covariance_normal{0.0};
  double residual{0.0};
  double source_support{0.0};
  double subpixel_offset{0.0};
  bool junction_excluded{false};
};

struct BoundaryEvidence {
  std::vector<BoundarySample> samples;
  bool subpixel_enabled{true};
};

[[nodiscard]] Result<BoundaryEvidence> estimate_boundaries(
    const RegionGraph& graph, const GrayImage& image,
    const std::vector<float>& reliability_confidence, const BoundaryConfig& config = {});

}  // namespace vectorai::binary
