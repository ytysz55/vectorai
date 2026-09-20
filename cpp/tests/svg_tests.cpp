#include <cassert>
#include <cstddef>
#include <string>
#include <vector>

#include "vectorai/core/svg.hpp"

namespace {

vectorai::binary::SelectedModel rectangle_model() {
  using vectorai::binary::CandidateKind;
  using vectorai::binary::Point2d;
  using vectorai::binary::SegmentKind;
  using vectorai::binary::ShapeCandidate;
  using vectorai::binary::VectorSegment;

  const std::vector<Point2d> points{{1.0, 2.0}, {9.0, 2.0}, {9.0, 6.0}, {1.0, 6.0}};
  ShapeCandidate shape;
  shape.kind = CandidateKind::kRectangle;
  shape.complexity = 1.0;
  for (std::size_t index = 0U; index < points.size(); ++index) {
    const Point2d start = points[index];
    const Point2d end = points[(index + 1U) % points.size()];
    shape.segments.push_back(
        VectorSegment{SegmentKind::kLine, start, start, end, end});
  }
  return vectorai::binary::SelectedModel{{1U, 0U}, {shape}, 0.03};
}

void test_svg_is_canonical_and_minimal() {
  const auto result = vectorai::binary::export_svg(
      rectangle_model(), vectorai::binary::SvgExportConfig{12U, 8U, "#112233", 6U});
  assert(result);
  const std::string expected =
      "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"12\" height=\"8\" "
      "viewBox=\"0 0 12 8\">\n"
      "  <path fill=\"#112233\" fill-rule=\"evenodd\" "
      "d=\"M1 2 L9 2 L9 6 L1 6 L1 2 Z\"/>\n"
      "</svg>\n";
  assert(result.value().content == expected);
  assert(result.value().path_count == 1U);
  assert(result.value().segment_count == 4U);
  assert(result.value().node_count == 4U);
}

void test_export_is_byte_deterministic() {
  const auto first = vectorai::binary::export_svg(
      rectangle_model(), vectorai::binary::SvgExportConfig{12U, 8U});
  const auto second = vectorai::binary::export_svg(
      rectangle_model(), vectorai::binary::SvgExportConfig{12U, 8U});
  assert(first && second);
  assert(first.value().content == second.value().content);
}

void test_empty_model_exports_transparent_document() {
  const vectorai::binary::SelectedModel empty{{0U, 0U}, {}, 0.0};
  const auto result =
      vectorai::binary::export_svg(empty, vectorai::binary::SvgExportConfig{3U, 2U});
  assert(result);
  assert(result.value().path_count == 0U);
  assert(result.value().content.find("<path") == std::string::npos);
}

void test_unsafe_fill_and_topology_mismatch_are_rejected() {
  auto model = rectangle_model();
  const auto unsafe = vectorai::binary::export_svg(
      model, vectorai::binary::SvgExportConfig{12U, 8U, "url(https://bad)", 6U});
  assert(!unsafe);
  model.topology.holes = 1U;
  const auto mismatch =
      vectorai::binary::export_svg(model, vectorai::binary::SvgExportConfig{12U, 8U});
  assert(!mismatch);
}

void test_compound_paths_use_evenodd_for_holes() {
  auto model = rectangle_model();
  model.shapes.push_back(model.shapes.front());
  model.shapes.back().segments.clear();
  const std::vector<vectorai::binary::Point2d> inner{{3.0, 3.0}, {3.0, 5.0},
                                                     {7.0, 5.0}, {7.0, 3.0}};
  for (std::size_t index = 0U; index < inner.size(); ++index) {
    const auto start = inner[index];
    const auto end = inner[(index + 1U) % inner.size()];
    model.shapes.back().segments.push_back({vectorai::binary::SegmentKind::kLine, start,
                                            start, end, end});
  }
  model.topology.holes = 1U;
  const auto result =
      vectorai::binary::export_svg(model, vectorai::binary::SvgExportConfig{12U, 8U});
  assert(result);
  assert(result.value().path_count == 1U);
  assert(result.value().content.find("fill-rule=\"evenodd\"") != std::string::npos);
  assert(result.value().content.find(" Z M") != std::string::npos);
}

}  // namespace

int main() {
  test_svg_is_canonical_and_minimal();
  test_export_is_byte_deterministic();
  test_empty_model_exports_transparent_document();
  test_unsafe_fill_and_topology_mismatch_are_rejected();
  test_compound_paths_use_evenodd_for_holes();
  return 0;
}
