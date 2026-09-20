#pragma once

#include <cstddef>
#include <string>

#include "vectorai/core/model_selection.hpp"
#include "vectorai/core/result.hpp"

namespace vectorai::binary {

struct SvgExportConfig {
  std::size_t width{0};
  std::size_t height{0};
  std::string fill{"#000000"};
  std::size_t decimal_places{6U};
};

struct SvgDocument {
  std::string content;
  std::size_t path_count{0};
  std::size_t segment_count{0};
  std::size_t node_count{0};
};

[[nodiscard]] Result<SvgDocument> export_svg(const SelectedModel& model,
                                             const SvgExportConfig& config);

}  // namespace vectorai::binary
