#pragma once

#include <stdexcept>
#include <utility>
#include <variant>

#include "vectorai/core/error.hpp"

namespace vectorai {

template <typename T>
class [[nodiscard]] Result {
 public:
  static Result success(T value) { return Result(std::move(value)); }
  static Result failure(EngineError error) { return Result(std::move(error)); }

  [[nodiscard]] bool has_value() const noexcept {
    return std::holds_alternative<T>(storage_);
  }

  [[nodiscard]] explicit operator bool() const noexcept { return has_value(); }

  T& value() {
    if (!has_value()) {
      throw std::logic_error("attempted to read a failed VectorAI Result");
    }
    return std::get<T>(storage_);
  }

  const T& value() const {
    if (!has_value()) {
      throw std::logic_error("attempted to read a failed VectorAI Result");
    }
    return std::get<T>(storage_);
  }

  EngineError& error() {
    if (has_value()) {
      throw std::logic_error("attempted to read an error from a successful VectorAI Result");
    }
    return std::get<EngineError>(storage_);
  }

  const EngineError& error() const {
    if (has_value()) {
      throw std::logic_error("attempted to read an error from a successful VectorAI Result");
    }
    return std::get<EngineError>(storage_);
  }

 private:
  explicit Result(T value) : storage_(std::move(value)) {}
  explicit Result(EngineError error) : storage_(std::move(error)) {}

  std::variant<T, EngineError> storage_;
};

template <>
class [[nodiscard]] Result<void> {
 public:
  static Result success() { return Result(std::monostate{}); }
  static Result failure(EngineError error) { return Result(std::move(error)); }

  [[nodiscard]] bool has_value() const noexcept {
    return std::holds_alternative<std::monostate>(storage_);
  }

  [[nodiscard]] explicit operator bool() const noexcept { return has_value(); }

  void value() const {
    if (!has_value()) {
      throw std::logic_error("attempted to read a failed VectorAI Result");
    }
  }

  EngineError& error() {
    if (has_value()) {
      throw std::logic_error("attempted to read an error from a successful VectorAI Result");
    }
    return std::get<EngineError>(storage_);
  }

  const EngineError& error() const {
    if (has_value()) {
      throw std::logic_error("attempted to read an error from a successful VectorAI Result");
    }
    return std::get<EngineError>(storage_);
  }

 private:
  explicit Result(std::monostate value) : storage_(value) {}
  explicit Result(EngineError error) : storage_(std::move(error)) {}

  std::variant<std::monostate, EngineError> storage_;
};

}  // namespace vectorai
