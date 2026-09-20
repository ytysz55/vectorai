#include "vectorai/core/region_graph.hpp"

#include <algorithm>
#include <array>
#include <cstddef>
#include <cstdint>
#include <limits>
#include <map>
#include <set>
#include <string>
#include <tuple>
#include <utility>
#include <vector>

namespace vectorai::binary {
namespace {

[[nodiscard]] EngineError graph_error(ErrorCode code, std::string message) {
  EngineError error;
  error.code = code;
  error.stage = Stage::kTopology;
  error.message = std::move(message);
  return error;
}

using PointKey = std::pair<std::int32_t, std::int32_t>;

[[nodiscard]] std::uint64_t get_vertex(RegionGraph& graph, std::map<PointKey, std::uint64_t>& ids,
                                       GridPoint point) {
  const PointKey key{point.x, point.y};
  const auto existing = ids.find(key);
  if (existing != ids.end()) {
    return existing->second;
  }
  const std::uint64_t id = static_cast<std::uint64_t>(graph.vertices.size());
  graph.vertices.push_back(GraphVertex{id, point, {}});
  ids.emplace(key, id);
  return id;
}

void add_boundary_pair(RegionGraph& graph, std::map<PointKey, std::uint64_t>& vertex_ids,
                       GridPoint origin, GridPoint target) {
  const std::uint64_t origin_id = get_vertex(graph, vertex_ids, origin);
  const std::uint64_t target_id = get_vertex(graph, vertex_ids, target);
  const std::uint64_t foreground_id = static_cast<std::uint64_t>(graph.half_edges.size());
  const std::uint64_t background_id = foreground_id + 1U;
  const std::uint64_t canonical_id = static_cast<std::uint64_t>(graph.canonical_edge_count++);
  graph.half_edges.push_back(HalfEdge{foreground_id, origin_id, target_id, background_id,
                                      foreground_id, 1U, canonical_id});
  graph.half_edges.push_back(HalfEdge{background_id, target_id, origin_id, foreground_id,
                                      background_id, 0U, canonical_id});
  graph.vertices[origin_id].outgoing_half_edges.push_back(foreground_id);
  graph.vertices[target_id].outgoing_half_edges.push_back(background_id);
}

[[nodiscard]] int direction(const RegionGraph& graph, const HalfEdge& edge) {
  const GridPoint origin = graph.vertices[edge.origin].position;
  const GridPoint target = graph.vertices[edge.target].position;
  const std::int32_t dx = target.x - origin.x;
  const std::int32_t dy = target.y - origin.y;
  if (dx == 1 && dy == 0) {
    return 0;
  }
  if (dx == 0 && dy == 1) {
    return 1;
  }
  if (dx == -1 && dy == 0) {
    return 2;
  }
  if (dx == 0 && dy == -1) {
    return 3;
  }
  return -1;
}

[[nodiscard]] int turn_rank(int current, int next) {
  const int turn = (next - current + 4) % 4;
  constexpr std::array<int, 4U> ranks{1, 0, 3, 2};
  return ranks[static_cast<std::size_t>(turn)];
}

[[nodiscard]] Result<void> link_next_edges(RegionGraph& graph) {
  for (auto& edge : graph.half_edges) {
    const int current_direction = direction(graph, edge);
    if (current_direction < 0) {
      return Result<void>::failure(
          graph_error(ErrorCode::kNonManifoldGraph, "half-edge is not a unit grid segment"));
    }
    const auto& outgoing = graph.vertices[edge.target].outgoing_half_edges;
    std::tuple<int, std::uint64_t> best{std::numeric_limits<int>::max(),
                                       std::numeric_limits<std::uint64_t>::max()};
    bool found = false;
    for (const std::uint64_t candidate_id : outgoing) {
      const HalfEdge& candidate = graph.half_edges[candidate_id];
      if (candidate.face != edge.face) {
        continue;
      }
      const int candidate_direction = direction(graph, candidate);
      const std::tuple<int, std::uint64_t> score{turn_rank(current_direction, candidate_direction),
                                                 candidate_id};
      if (!found || score < best) {
        best = score;
        found = true;
      }
    }
    if (!found) {
      return Result<void>::failure(graph_error(
          ErrorCode::kNonManifoldGraph, "half-edge target has no same-face continuation"));
    }
    edge.next = std::get<1>(best);
  }
  return Result<void>::success();
}

[[nodiscard]] Result<void> populate_cycles(RegionGraph& graph) {
  std::vector<std::uint8_t> visited(graph.half_edges.size(), 0U);
  for (auto& face : graph.faces) {
    face.boundary_cycles.clear();
  }
  for (const HalfEdge& start : graph.half_edges) {
    if (visited[start.id] != 0U) {
      continue;
    }
    std::uint64_t current = start.id;
    std::uint64_t minimum = start.id;
    std::size_t steps = 0U;
    do {
      if (current >= graph.half_edges.size() || visited[current] != 0U) {
        return Result<void>::failure(
            graph_error(ErrorCode::kNonManifoldGraph, "half-edge cycle is not simple and closed"));
      }
      const HalfEdge& edge = graph.half_edges[current];
      if (edge.face != start.face) {
        return Result<void>::failure(
            graph_error(ErrorCode::kNonManifoldGraph, "half-edge cycle changes face"));
      }
      visited[current] = 1U;
      minimum = std::min(minimum, current);
      current = edge.next;
      ++steps;
      if (steps > graph.half_edges.size()) {
        return Result<void>::failure(
            graph_error(ErrorCode::kNonManifoldGraph, "half-edge cycle exceeds graph size"));
      }
    } while (current != start.id);
    graph.faces[start.face].boundary_cycles.push_back(minimum);
  }
  for (auto& face : graph.faces) {
    std::sort(face.boundary_cycles.begin(), face.boundary_cycles.end());
  }
  return Result<void>::success();
}

}  // namespace

Result<RegionGraph> build_region_graph(const BinaryMask& mask) {
  if (mask.width == 0U || mask.height == 0U || mask.width > kMaxPixels ||
      mask.height > kMaxPixels || mask.width > kMaxPixels / mask.height ||
      mask.width * mask.height > kMaxPixels || mask.foreground.size() != mask.width * mask.height) {
    return Result<RegionGraph>::failure(
        graph_error(ErrorCode::kResourceLimit, "binary mask dimensions are invalid"));
  }
  if (std::any_of(mask.foreground.begin(), mask.foreground.end(),
                  [](std::uint8_t value) { return value > 1U; })) {
    return Result<RegionGraph>::failure(
        graph_error(ErrorCode::kInternalInvariantViolation, "binary mask is not binary"));
  }

  RegionGraph graph;
  graph.faces = {RegionFace{0U, false, {}}, RegionFace{1U, true, {}}};
  std::map<PointKey, std::uint64_t> vertex_ids;
  for (std::size_t y = 0U; y < mask.height; ++y) {
    for (std::size_t x = 0U; x < mask.width; ++x) {
      if (!mask.at(x, y)) {
        continue;
      }
      const auto x0 = static_cast<std::int32_t>(x);
      const auto y0 = static_cast<std::int32_t>(y);
      const auto x1 = static_cast<std::int32_t>(x + 1U);
      const auto y1 = static_cast<std::int32_t>(y + 1U);
      if (y == 0U || !mask.at(x, y - 1U)) {
        add_boundary_pair(graph, vertex_ids, GridPoint{x0, y0}, GridPoint{x1, y0});
      }
      if (x + 1U == mask.width || !mask.at(x + 1U, y)) {
        add_boundary_pair(graph, vertex_ids, GridPoint{x1, y0}, GridPoint{x1, y1});
      }
      if (y + 1U == mask.height || !mask.at(x, y + 1U)) {
        add_boundary_pair(graph, vertex_ids, GridPoint{x1, y1}, GridPoint{x0, y1});
      }
      if (x == 0U || !mask.at(x - 1U, y)) {
        add_boundary_pair(graph, vertex_ids, GridPoint{x0, y1}, GridPoint{x0, y0});
      }
    }
  }

  if (graph.half_edges.empty()) {
    return Result<RegionGraph>::success(std::move(graph));
  }
  auto linked = link_next_edges(graph);
  if (!linked) {
    return Result<RegionGraph>::failure(linked.error());
  }
  auto cycles = populate_cycles(graph);
  if (!cycles) {
    return Result<RegionGraph>::failure(cycles.error());
  }
  auto validation = validate_region_graph(graph);
  if (!validation) {
    return Result<RegionGraph>::failure(validation.error());
  }
  return Result<RegionGraph>::success(std::move(graph));
}

Result<void> validate_region_graph(const RegionGraph& graph) {
  if (graph.faces.size() != 2U || graph.faces[0].id != 0U || graph.faces[0].foreground ||
      graph.faces[1].id != 1U || !graph.faces[1].foreground) {
    return Result<void>::failure(
        graph_error(ErrorCode::kNonManifoldGraph, "region graph faces are not canonical"));
  }
  if (graph.half_edges.size() != graph.canonical_edge_count * 2U) {
    return Result<void>::failure(
        graph_error(ErrorCode::kNonManifoldGraph, "canonical edge count does not match twins"));
  }
  for (std::size_t index = 0U; index < graph.vertices.size(); ++index) {
    const GraphVertex& vertex = graph.vertices[index];
    if (vertex.id != index) {
      return Result<void>::failure(
          graph_error(ErrorCode::kNonManifoldGraph, "vertex identifiers are not contiguous"));
    }
    for (const std::uint64_t edge_id : vertex.outgoing_half_edges) {
      if (edge_id >= graph.half_edges.size() || graph.half_edges[edge_id].origin != vertex.id) {
        return Result<void>::failure(
            graph_error(ErrorCode::kNonManifoldGraph, "vertex outgoing relation is invalid"));
      }
    }
  }

  std::vector<std::uint8_t> visited(graph.half_edges.size(), 0U);
  std::vector<std::uint8_t> canonical_counts(graph.canonical_edge_count, 0U);
  for (std::size_t index = 0U; index < graph.half_edges.size(); ++index) {
    const HalfEdge& edge = graph.half_edges[index];
    if (edge.id != index || edge.origin >= graph.vertices.size() ||
        edge.target >= graph.vertices.size() || edge.origin == edge.target ||
        edge.twin >= graph.half_edges.size() || edge.next >= graph.half_edges.size() ||
        edge.face >= graph.faces.size() || edge.canonical_edge >= graph.canonical_edge_count) {
      return Result<void>::failure(
          graph_error(ErrorCode::kNonManifoldGraph, "half-edge index relation is out of range"));
    }
    const HalfEdge& twin = graph.half_edges[edge.twin];
    const HalfEdge& next = graph.half_edges[edge.next];
    if (twin.twin != edge.id || twin.origin != edge.target || twin.target != edge.origin ||
        twin.face == edge.face || twin.canonical_edge != edge.canonical_edge) {
      return Result<void>::failure(
          graph_error(ErrorCode::kNonManifoldGraph, "half-edge twin invariant failed"));
    }
    if (next.face != edge.face || next.origin != edge.target) {
      return Result<void>::failure(
          graph_error(ErrorCode::kNonManifoldGraph, "half-edge next invariant failed"));
    }
    if (direction(graph, edge) < 0) {
      return Result<void>::failure(
          graph_error(ErrorCode::kNonManifoldGraph, "half-edge geometry is not a unit segment"));
    }
    ++canonical_counts[edge.canonical_edge];
  }
  if (std::any_of(canonical_counts.begin(), canonical_counts.end(),
                  [](std::uint8_t count) { return count != 2U; })) {
    return Result<void>::failure(
        graph_error(ErrorCode::kNonManifoldGraph, "canonical edge is not shared by two twins"));
  }

  for (const HalfEdge& start : graph.half_edges) {
    if (visited[start.id] != 0U) {
      continue;
    }
    std::uint64_t current = start.id;
    std::size_t steps = 0U;
    do {
      if (current >= graph.half_edges.size() || visited[current] != 0U) {
        return Result<void>::failure(
            graph_error(ErrorCode::kNonManifoldGraph, "cycle traversal encountered reused edge"));
      }
      visited[current] = 1U;
      current = graph.half_edges[current].next;
      ++steps;
      if (steps > graph.half_edges.size()) {
        return Result<void>::failure(
            graph_error(ErrorCode::kNonManifoldGraph, "cycle traversal did not terminate"));
      }
    } while (current != start.id);
  }
  return Result<void>::success();
}

Result<std::vector<std::vector<std::uint64_t>>> extract_face_cycles(const RegionGraph& graph,
                                                                    std::uint64_t face_id) {
  auto validation = validate_region_graph(graph);
  if (!validation) {
    return Result<std::vector<std::vector<std::uint64_t>>>::failure(validation.error());
  }
  if (face_id >= graph.faces.size()) {
    return Result<std::vector<std::vector<std::uint64_t>>>::failure(
        graph_error(ErrorCode::kNonManifoldGraph, "requested face does not exist"));
  }
  std::vector<std::vector<std::uint64_t>> cycles;
  for (const std::uint64_t start : graph.faces[face_id].boundary_cycles) {
    std::vector<std::uint64_t> cycle;
    std::uint64_t current = start;
    do {
      cycle.push_back(current);
      current = graph.half_edges[current].next;
    } while (current != start);
    cycles.push_back(std::move(cycle));
  }
  return Result<std::vector<std::vector<std::uint64_t>>>::success(std::move(cycles));
}

}  // namespace vectorai::binary
