#include <algorithm>
#include <cctype>
#include <cstddef>
#include <cstdint>
#include <exception>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <locale>
#include <sstream>
#include <string>
#include <utility>
#include <vector>

#include "vectorai/core/binary.hpp"
#include "vectorai/core/boundary.hpp"
#include "vectorai/core/fitting.hpp"
#include "vectorai/core/model_selection.hpp"
#include "vectorai/core/region_graph.hpp"
#include "vectorai/core/svg.hpp"

namespace {

struct Arguments {
  std::filesystem::path input;
  std::filesystem::path output;
  std::filesystem::path report;
  std::filesystem::path reliability;
  float threshold{-1.0F};
  bool subpixel{true};
  bool bezier_only{false};
};

[[nodiscard]] std::string escape_json(const std::string& value) {
  std::ostringstream stream;
  for (const char character : value) {
    switch (character) {
      case '\\':
        stream << "\\\\";
        break;
      case '"':
        stream << "\\\"";
        break;
      case '\n':
        stream << "\\n";
        break;
      case '\r':
        stream << "\\r";
        break;
      case '\t':
        stream << "\\t";
        break;
      default:
        if (static_cast<unsigned char>(character) < 0x20U) {
          stream << "?";
        } else {
          stream << character;
        }
    }
  }
  return stream.str();
}

[[nodiscard]] bool write_text(const std::filesystem::path& path, const std::string& content) {
  std::ofstream stream(path, std::ios::binary | std::ios::trunc);
  if (!stream) {
    return false;
  }
  stream.write(content.data(), static_cast<std::streamsize>(content.size()));
  return static_cast<bool>(stream);
}

void write_failure(const std::filesystem::path& path, const vectorai::EngineError& error) {
  std::ostringstream stream;
  stream.imbue(std::locale::classic());
  stream << "{\n  \"status\": \"failed\",\n  \"code\": \""
         << vectorai::to_string(error.code) << "\",\n  \"stage\": \""
         << vectorai::to_string(error.stage) << "\",\n  \"message\": \""
         << escape_json(error.message) << "\"\n}\n";
  static_cast<void>(write_text(path, stream.str()));
}

[[nodiscard]] vectorai::EngineError cli_error(vectorai::ErrorCode code, vectorai::Stage stage,
                                               std::string message) {
  vectorai::EngineError error;
  error.code = code;
  error.stage = stage;
  error.message = std::move(message);
  return error;
}

[[nodiscard]] vectorai::Result<Arguments> parse_arguments(int argc, char** argv) {
  Arguments arguments;
  for (int index = 1; index < argc; ++index) {
    const std::string option = argv[index];
    if ((option == "--input" || option == "--output" || option == "--report" ||
         option == "--reliability" || option == "--threshold" || option == "--subpixel") &&
        index + 1 >= argc) {
      return vectorai::Result<Arguments>::failure(cli_error(
          vectorai::ErrorCode::kUnsupportedInput, vectorai::Stage::kDecode,
          "missing value for command-line option " + option));
    }
    if (option == "--input") {
      arguments.input = argv[++index];
    } else if (option == "--output") {
      arguments.output = argv[++index];
    } else if (option == "--report") {
      arguments.report = argv[++index];
    } else if (option == "--reliability") {
      arguments.reliability = argv[++index];
    } else if (option == "--threshold") {
      try {
        arguments.threshold = std::stof(argv[++index]);
      } catch (const std::exception&) {
        return vectorai::Result<Arguments>::failure(cli_error(
            vectorai::ErrorCode::kUnsupportedInput, vectorai::Stage::kSegmentation,
            "threshold must be a finite number"));
      }
    } else if (option == "--subpixel") {
      const std::string value = argv[++index];
      if (value != "0" && value != "1") {
        return vectorai::Result<Arguments>::failure(cli_error(
            vectorai::ErrorCode::kUnsupportedInput, vectorai::Stage::kBoundary,
            "subpixel must be 0 or 1"));
      }
      arguments.subpixel = value == "1";
    } else if (option == "--bezier-only") {
      arguments.bezier_only = true;
    } else {
      return vectorai::Result<Arguments>::failure(cli_error(
          vectorai::ErrorCode::kUnsupportedInput, vectorai::Stage::kDecode,
          "unknown command-line option " + option));
    }
  }
  if (arguments.input.empty() || arguments.output.empty() || arguments.report.empty()) {
    return vectorai::Result<Arguments>::failure(cli_error(
        vectorai::ErrorCode::kUnsupportedInput, vectorai::Stage::kDecode,
        "--input, --output, and --report are required"));
  }
  return vectorai::Result<Arguments>::success(std::move(arguments));
}

[[nodiscard]] bool whitespace(int value) {
  return value != std::char_traits<char>::eof() &&
         std::isspace(static_cast<unsigned char>(value)) != 0;
}

[[nodiscard]] vectorai::Result<std::string> read_pgm_token(std::ifstream& stream) {
  while (stream) {
    const int value = stream.peek();
    if (whitespace(value)) {
      static_cast<void>(stream.get());
      continue;
    }
    if (value == '#') {
      std::string ignored;
      std::getline(stream, ignored);
      continue;
    }
    break;
  }
  std::string token;
  while (stream) {
    const int value = stream.peek();
    if (whitespace(value) || value == '#') {
      break;
    }
    token.push_back(static_cast<char>(stream.get()));
  }
  if (token.empty()) {
    return vectorai::Result<std::string>::failure(cli_error(
        vectorai::ErrorCode::kDecodeError, vectorai::Stage::kDecode,
        "unexpected end of PGM header"));
  }
  return vectorai::Result<std::string>::success(std::move(token));
}

[[nodiscard]] vectorai::Result<std::size_t> parse_size(const std::string& token) {
  try {
    std::size_t consumed = 0U;
    const unsigned long long parsed = std::stoull(token, &consumed, 10);
    if (consumed != token.size() || parsed > std::numeric_limits<std::size_t>::max()) {
      throw std::out_of_range("PGM size");
    }
    return vectorai::Result<std::size_t>::success(static_cast<std::size_t>(parsed));
  } catch (const std::exception&) {
    return vectorai::Result<std::size_t>::failure(cli_error(
        vectorai::ErrorCode::kDecodeError, vectorai::Stage::kDecode,
        "invalid numeric field in PGM header"));
  }
}

[[nodiscard]] vectorai::Result<vectorai::binary::GrayImage> read_pgm(
    const std::filesystem::path& path) {
  std::ifstream stream(path, std::ios::binary);
  if (!stream) {
    return vectorai::Result<vectorai::binary::GrayImage>::failure(cli_error(
        vectorai::ErrorCode::kDecodeError, vectorai::Stage::kDecode,
        "cannot open native evidence input"));
  }
  auto magic = read_pgm_token(stream);
  auto width_token = read_pgm_token(stream);
  auto height_token = read_pgm_token(stream);
  auto maximum_token = read_pgm_token(stream);
  if (!magic || !width_token || !height_token || !maximum_token) {
    return vectorai::Result<vectorai::binary::GrayImage>::failure(cli_error(
        vectorai::ErrorCode::kDecodeError, vectorai::Stage::kDecode,
        "incomplete PGM header"));
  }
  if (magic.value() != "P5") {
    return vectorai::Result<vectorai::binary::GrayImage>::failure(cli_error(
        vectorai::ErrorCode::kUnsupportedInput, vectorai::Stage::kDecode,
        "native evidence input must be binary PGM P5"));
  }
  auto width = parse_size(width_token.value());
  auto height = parse_size(height_token.value());
  auto maximum = parse_size(maximum_token.value());
  if (!width || !height || !maximum || maximum.value() != 255U || width.value() == 0U ||
      height.value() == 0U || width.value() > vectorai::binary::kMaxPixels ||
      height.value() > vectorai::binary::kMaxPixels ||
      width.value() > vectorai::binary::kMaxPixels / height.value()) {
    return vectorai::Result<vectorai::binary::GrayImage>::failure(cli_error(
        vectorai::ErrorCode::kResourceLimit, vectorai::Stage::kDecode,
        "PGM dimensions or maximum value are unsupported"));
  }
  const int delimiter = stream.get();
  if (!whitespace(delimiter)) {
    return vectorai::Result<vectorai::binary::GrayImage>::failure(cli_error(
        vectorai::ErrorCode::kDecodeError, vectorai::Stage::kDecode,
        "PGM header is not followed by binary pixels"));
  }
  const std::size_t count = width.value() * height.value();
  std::vector<std::uint8_t> bytes(count, 0U);
  stream.read(reinterpret_cast<char*>(bytes.data()), static_cast<std::streamsize>(bytes.size()));
  if (stream.gcount() != static_cast<std::streamsize>(bytes.size())) {
    return vectorai::Result<vectorai::binary::GrayImage>::failure(cli_error(
        vectorai::ErrorCode::kDecodeError, vectorai::Stage::kDecode,
        "PGM pixel payload is truncated"));
  }
  vectorai::binary::GrayImage image;
  image.width = width.value();
  image.height = height.value();
  image.foreground_evidence.reserve(count);
  for (const std::uint8_t value : bytes) {
    image.foreground_evidence.push_back(static_cast<float>(value) / 255.0F);
  }
  return vectorai::Result<vectorai::binary::GrayImage>::success(std::move(image));
}

[[nodiscard]] std::string success_report(
    const vectorai::binary::GrayImage& image,
    const vectorai::binary::SegmentationResult& segmentation,
    const vectorai::binary::RegionGraph& graph,
    const vectorai::binary::BoundaryEvidence& boundaries,
    const std::vector<vectorai::binary::CycleCandidates>& cycles,
    const vectorai::binary::SelectedModel& model,
    const vectorai::binary::SvgDocument& document) {
  std::size_t candidate_count = 0U;
  for (const auto& cycle : cycles) {
    candidate_count += cycle.candidates.size();
  }
  std::ostringstream stream;
  stream.imbue(std::locale::classic());
  stream << std::fixed << std::setprecision(9)
         << "{\n  \"status\": \"success\",\n  \"width\": " << image.width
         << ",\n  \"height\": " << image.height << ",\n  \"threshold\": "
         << segmentation.threshold << ",\n  \"components\": "
         << segmentation.topology.components << ",\n  \"holes\": "
         << segmentation.topology.holes << ",\n  \"euler\": "
         << segmentation.topology.euler_characteristic()
         << ",\n  \"canonical_edges\": " << graph.canonical_edge_count
         << ",\n  \"boundary_samples\": " << boundaries.samples.size()
         << ",\n  \"candidate_count\": " << candidate_count
         << ",\n  \"selected_shapes\": " << model.shapes.size()
         << ",\n  \"segments\": " << document.segment_count
         << ",\n  \"nodes\": " << document.node_count << "\n}\n";
  return stream.str();
}

}  // namespace

int main(int argc, char** argv) {
  const auto parsed = parse_arguments(argc, argv);
  if (!parsed) {
    std::cerr << parsed.error().message << '\n';
    return 2;
  }
  const Arguments& arguments = parsed.value();
  const auto image = read_pgm(arguments.input);
  if (!image) {
    write_failure(arguments.report, image.error());
    return 3;
  }
  const auto segmentation = vectorai::binary::segment(image.value(), arguments.threshold);
  if (!segmentation) {
    write_failure(arguments.report, segmentation.error());
    return 4;
  }
  const auto graph = vectorai::binary::build_region_graph(segmentation.value().mask);
  if (!graph) {
    write_failure(arguments.report, graph.error());
    return 5;
  }
  std::vector<float> reliability_confidence;
  if (!arguments.reliability.empty()) {
    const auto reliability = read_pgm(arguments.reliability);
    if (!reliability || reliability.value().width != image.value().width ||
        reliability.value().height != image.value().height) {
      const auto error =
          reliability
              ? cli_error(vectorai::ErrorCode::kInternalInvariantViolation,
                          vectorai::Stage::kReliability,
                          "reliability map dimensions do not match evidence")
              : reliability.error();
      write_failure(arguments.report, error);
      return 6;
    }
    reliability_confidence = reliability.value().foreground_evidence;
  }
  vectorai::binary::BoundaryConfig boundary_config;
  boundary_config.threshold = segmentation.value().threshold;
  boundary_config.enable_subpixel = arguments.subpixel;
  const auto boundaries = vectorai::binary::estimate_boundaries(
      graph.value(), image.value(), reliability_confidence, boundary_config);
  if (!boundaries) {
    write_failure(arguments.report, boundaries.error());
    return 6;
  }
  auto candidates = vectorai::binary::generate_candidates(graph.value(), boundaries.value());
  if (!candidates) {
    write_failure(arguments.report, candidates.error());
    return 7;
  }
  if (arguments.bezier_only) {
    for (auto& cycle : candidates.value()) {
      cycle.candidates.erase(
          std::remove_if(cycle.candidates.begin(), cycle.candidates.end(),
                         [](const vectorai::binary::ShapeCandidate& candidate) {
                           return candidate.kind != vectorai::binary::CandidateKind::kBezier;
                         }),
          cycle.candidates.end());
    }
  }
  const auto model =
      vectorai::binary::select_model(candidates.value(), segmentation.value().topology);
  if (!model) {
    write_failure(arguments.report, model.error());
    return 8;
  }
  const auto document = vectorai::binary::export_svg(
      model.value(), vectorai::binary::SvgExportConfig{image.value().width, image.value().height});
  if (!document) {
    write_failure(arguments.report, document.error());
    return 9;
  }
  if (!write_text(arguments.output, document.value().content)) {
    const auto error = cli_error(vectorai::ErrorCode::kExportFailed, vectorai::Stage::kExport,
                                 "cannot write SVG output");
    write_failure(arguments.report, error);
    return 10;
  }
  if (!write_text(arguments.report,
                  success_report(image.value(), segmentation.value(), graph.value(),
                                 boundaries.value(), candidates.value(), model.value(),
                                 document.value()))) {
    std::cerr << "cannot write native report\n";
    return 11;
  }
  return 0;
}
