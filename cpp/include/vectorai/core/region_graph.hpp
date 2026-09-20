#pragma once

#include <cstddef>
#include <cstdint>
#include <vector>

#include "vectorai/core/binary.hpp"
#include "vectorai/core/result.hpp"

namespace vectorai::binary {

struct GridPoint {
  std::int32_t x{0};
  std::int32_t y{0};

  [[nodiscard]] bool operator==(const GridPoint& other) const noexcept {
    return x == other.x && y == other.y;
  }
};

struct GraphVertex {
  std::uint64_t id{0};
  GridPoint position;
  std::vector<std::uint64_t> outgoing_half_edges;
};

struct HalfEdge {
  std::uint64_t id{0};
  std::uint64_t origin{0};
  std::uint64_t target{0};
  std::uint64_t twin{0};
  std::uint64_t next{0};
  std::uint64_t face{0};
  std::uint64_t canonical_edge{0};
};

struct RegionFace {
  std::uint64_t id{0};
  bool foreground{false};
  std::vector<std::uint64_t> boundary_cycles;
};

struct RegionGraph {
  std::vector<GraphVertex> vertices;
  std::vector<HalfEdge> half_edges;
  std::vector<RegionFace> faces;
  std::size_t canonical_edge_count{0};
};

[[nodiscard]] Result<RegionGraph> build_region_graph(const BinaryMask& mask);
[[nodiscard]] Result<void> validate_region_graph(const RegionGraph& graph);
[[nodiscard]] Result<std::vector<std::vector<std::uint64_t>>> extract_face_cycles(
    const RegionGraph& graph, std::uint64_t face_id);

}  // namespace vectorai::binary
