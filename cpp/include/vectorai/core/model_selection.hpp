#pragma once

#include <cstddef>
#include <vector>

#include "vectorai/core/binary.hpp"
#include "vectorai/core/fitting.hpp"
#include "vectorai/core/result.hpp"

namespace vectorai::binary {

struct ModelSelectionConfig {
  double fidelity_weight{1.0};
  double complexity_weight{0.08};
  double primitive_bonus{0.05};
  double maximum_fit_error{0.75};
  std::size_t maximum_segments_per_shape{4096U};
};

struct SelectedModel {
  TopologySummary topology;
  std::vector<ShapeCandidate> shapes;
  double objective{0.0};
};

[[nodiscard]] Result<void> validate_selected_model(const SelectedModel& model);
[[nodiscard]] Result<SelectedModel> select_model(
    const std::vector<CycleCandidates>& cycles, const TopologySummary& topology,
    const ModelSelectionConfig& config = {});

}  // namespace vectorai::binary
