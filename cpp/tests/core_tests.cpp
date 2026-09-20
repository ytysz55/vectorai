#include <cassert>
#include <stdexcept>

#include "vectorai/core/error.hpp"
#include "vectorai/core/result.hpp"
#include "vectorai/core/version.hpp"

namespace {

void test_string_contracts() {
  using vectorai::ErrorCode;
  using vectorai::RunStatus;
  using vectorai::Stage;

  assert(vectorai::to_string(ErrorCode::kUnsupportedInput) == "UNSUPPORTED_INPUT");
  assert(vectorai::to_string(ErrorCode::kInternalInvariantViolation) ==
         "INTERNAL_INVARIANT_VIOLATION");
  assert(vectorai::to_string(Stage::kCandidateGeneration) == "candidate_generation");
  assert(vectorai::to_string(RunStatus::kNeedsReview) == "needs_review");
  assert(vectorai::kVersion == "0.1.0");
}

void test_success_result() {
  auto result = vectorai::Result<int>::success(42);
  assert(result.has_value());
  assert(static_cast<bool>(result));
  assert(result.value() == 42);

  bool threw = false;
  try {
    static_cast<void>(result.error());
  } catch (const std::logic_error&) {
    threw = true;
  }
  assert(threw);
}

void test_failure_result() {
  vectorai::EngineError error{
      vectorai::ErrorCode::kDecodeError,
      vectorai::Stage::kDecode,
      "invalid image payload",
      false,
      {},
      {{"media_type", "image/png"}},
  };

  auto result = vectorai::Result<int>::failure(std::move(error));
  assert(!result.has_value());
  assert(result.error().code == vectorai::ErrorCode::kDecodeError);
  assert(result.error().stage == vectorai::Stage::kDecode);
  assert(result.error().context.at("media_type") == "image/png");
}

void test_void_result() {
  const auto result = vectorai::Result<void>::success();
  assert(result.has_value());
  result.value();
}

}  // namespace

int main() {
  test_string_contracts();
  test_success_result();
  test_failure_result();
  test_void_result();
  return 0;
}
