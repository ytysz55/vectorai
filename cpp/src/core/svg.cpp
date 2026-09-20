#include "vectorai/core/svg.hpp"

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <iomanip>
#include <locale>
#include <regex>
#include <sstream>
#include <string>
#include <utility>

namespace vectorai::binary {
namespace {

[[nodiscard]] EngineError export_error(ErrorCode code, std::string message) {
  EngineError error;
  error.code = code;
  error.stage = Stage::kExport;
  error.message = std::move(message);
  return error;
}

[[nodiscard]] std::string number(double value, std::size_t decimal_places) {
  const double epsilon = 0.5 * std::pow(10.0, -static_cast<double>(decimal_places));
  if (std::abs(value) < epsilon) {
    value = 0.0;
  }
  std::ostringstream stream;
  stream.imbue(std::locale::classic());
  stream << std::fixed << std::setprecision(static_cast<int>(decimal_places)) << value;
  std::string result = stream.str();
  const std::size_t decimal = result.find('.');
  if (decimal != std::string::npos) {
    while (!result.empty() && result.back() == '0') {
      result.pop_back();
    }
    if (!result.empty() && result.back() == '.') {
      result.pop_back();
    }
  }
  return result == "-0" ? "0" : result;
}

void append_point(std::ostringstream& stream, Point2d point, std::size_t decimals) {
  stream << number(point.x, decimals) << ' ' << number(point.y, decimals);
}

}  // namespace

Result<SvgDocument> export_svg(const SelectedModel& model, const SvgExportConfig& config) {
  const auto validation = validate_selected_model(model);
  if (!validation) {
    if (model.shapes.empty() && model.topology.components == 0U && model.topology.holes == 0U &&
        std::isfinite(model.objective)) {
      // An empty segmentation is a valid transparent SVG.
    } else {
      return Result<SvgDocument>::failure(validation.error());
    }
  }
  if (config.width == 0U || config.height == 0U || config.width > kMaxPixels ||
      config.height > kMaxPixels || config.width > kMaxPixels / config.height ||
      config.width * config.height > kMaxPixels || config.decimal_places > 9U) {
    return Result<SvgDocument>::failure(
        export_error(ErrorCode::kResourceLimit, "SVG dimensions or precision are invalid"));
  }
  static const std::regex color_pattern("^#[0-9A-Fa-f]{6}([0-9A-Fa-f]{2})?$");
  if (!std::regex_match(config.fill, color_pattern)) {
    return Result<SvgDocument>::failure(
        export_error(ErrorCode::kExportFailed, "SVG fill must be a hexadecimal color"));
  }

  std::ostringstream stream;
  stream.imbue(std::locale::classic());
  stream << "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"" << config.width
         << "\" height=\"" << config.height << "\" viewBox=\"0 0 " << config.width << ' '
         << config.height << "\">\n";

  SvgDocument document;
  if (!model.shapes.empty()) {
    stream << "  <path fill=\"" << config.fill
           << "\" fill-rule=\"evenodd\" d=\"";
    bool first_command = true;
    for (const ShapeCandidate& shape : model.shapes) {
      if (!first_command) {
        stream << ' ';
      }
      stream << 'M';
      append_point(stream, shape.segments.front().start, config.decimal_places);
      for (const VectorSegment& segment : shape.segments) {
        if (segment.kind == SegmentKind::kLine) {
          stream << " L";
          append_point(stream, segment.end, config.decimal_places);
        } else {
          stream << " C";
          append_point(stream, segment.control1, config.decimal_places);
          stream << ' ';
          append_point(stream, segment.control2, config.decimal_places);
          stream << ' ';
          append_point(stream, segment.end, config.decimal_places);
        }
        ++document.segment_count;
      }
      stream << " Z";
      first_command = false;
    }
    stream << "\"/>\n";
    document.path_count = 1U;
    document.node_count = document.segment_count;
  }
  stream << "</svg>\n";
  document.content = stream.str();
  return Result<SvgDocument>::success(std::move(document));
}

}  // namespace vectorai::binary
