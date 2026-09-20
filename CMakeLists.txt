cmake_minimum_required(VERSION 3.24)

project(
  VectorAI
  VERSION 0.1.0
  DESCRIPTION "Topology-first raster-to-vector reconstruction engine"
  LANGUAGES CXX
)

option(VECTORAI_BUILD_TESTS "Build VectorAI native tests" ON)
option(VECTORAI_WARNINGS_AS_ERRORS "Treat compiler warnings as errors" OFF)

add_library(vectorai_core STATIC
  cpp/src/core/binary.cpp
  cpp/src/core/boundary.cpp
  cpp/src/core/error.cpp
  cpp/src/core/fitting.cpp
  cpp/src/core/model_selection.cpp
  cpp/src/core/region_graph.cpp
  cpp/src/core/svg.cpp
)
add_library(VectorAI::core ALIAS vectorai_core)

target_include_directories(vectorai_core
  PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/cpp/include>
    $<INSTALL_INTERFACE:include>
)

target_compile_features(vectorai_core PUBLIC cxx_std_17)
set_target_properties(vectorai_core PROPERTIES
  CXX_EXTENSIONS OFF
  POSITION_INDEPENDENT_CODE ON
)

if(MSVC)
  target_compile_options(vectorai_core PRIVATE /W4 /permissive-)
  if(VECTORAI_WARNINGS_AS_ERRORS)
    target_compile_options(vectorai_core PRIVATE /WX)
  endif()
else()
  target_compile_options(vectorai_core PRIVATE -Wall -Wextra -Wpedantic)
  if(VECTORAI_WARNINGS_AS_ERRORS)
    target_compile_options(vectorai_core PRIVATE -Werror)
  endif()
endif()

add_executable(vectorai_binary_cli cpp/src/cli/binary_cli.cpp)
target_link_libraries(vectorai_binary_cli PRIVATE VectorAI::core)
target_compile_features(vectorai_binary_cli PRIVATE cxx_std_17)
set_target_properties(vectorai_binary_cli PROPERTIES CXX_EXTENSIONS OFF)

if(MSVC)
  target_compile_options(vectorai_binary_cli PRIVATE /W4 /permissive-)
  if(VECTORAI_WARNINGS_AS_ERRORS)
    target_compile_options(vectorai_binary_cli PRIVATE /WX)
  endif()
else()
  target_compile_options(vectorai_binary_cli PRIVATE -Wall -Wextra -Wpedantic)
  if(VECTORAI_WARNINGS_AS_ERRORS)
    target_compile_options(vectorai_binary_cli PRIVATE -Werror)
  endif()
endif()

include(CTest)
if(BUILD_TESTING AND VECTORAI_BUILD_TESTS)
  add_executable(vectorai_core_tests cpp/tests/core_tests.cpp)
  target_link_libraries(vectorai_core_tests PRIVATE VectorAI::core)
  target_compile_features(vectorai_core_tests PRIVATE cxx_std_17)
  set_target_properties(vectorai_core_tests PROPERTIES CXX_EXTENSIONS OFF)

  if(MSVC)
    target_compile_options(vectorai_core_tests PRIVATE /W4 /permissive-)
  else()
    target_compile_options(vectorai_core_tests PRIVATE -Wall -Wextra -Wpedantic)
  endif()

  add_test(NAME vectorai.core COMMAND vectorai_core_tests)

  add_executable(vectorai_binary_segmentation_tests
    cpp/tests/binary_segmentation_tests.cpp
  )
  target_link_libraries(vectorai_binary_segmentation_tests PRIVATE VectorAI::core)
  target_compile_features(vectorai_binary_segmentation_tests PRIVATE cxx_std_17)
  set_target_properties(vectorai_binary_segmentation_tests PROPERTIES CXX_EXTENSIONS OFF)

  if(MSVC)
    target_compile_options(vectorai_binary_segmentation_tests PRIVATE /W4 /permissive-)
  else()
    target_compile_options(vectorai_binary_segmentation_tests PRIVATE -Wall -Wextra -Wpedantic)
  endif()

  add_test(NAME vectorai.binary.segmentation COMMAND vectorai_binary_segmentation_tests)

  add_executable(vectorai_region_graph_tests cpp/tests/region_graph_tests.cpp)
  target_link_libraries(vectorai_region_graph_tests PRIVATE VectorAI::core)
  target_compile_features(vectorai_region_graph_tests PRIVATE cxx_std_17)
  set_target_properties(vectorai_region_graph_tests PROPERTIES CXX_EXTENSIONS OFF)

  if(MSVC)
    target_compile_options(vectorai_region_graph_tests PRIVATE /W4 /permissive-)
  else()
    target_compile_options(vectorai_region_graph_tests PRIVATE -Wall -Wextra -Wpedantic)
  endif()

  add_test(NAME vectorai.binary.region_graph COMMAND vectorai_region_graph_tests)

  add_executable(vectorai_boundary_tests cpp/tests/boundary_tests.cpp)
  target_link_libraries(vectorai_boundary_tests PRIVATE VectorAI::core)
  target_compile_features(vectorai_boundary_tests PRIVATE cxx_std_17)
  set_target_properties(vectorai_boundary_tests PROPERTIES CXX_EXTENSIONS OFF)

  if(MSVC)
    target_compile_options(vectorai_boundary_tests PRIVATE /W4 /permissive-)
  else()
    target_compile_options(vectorai_boundary_tests PRIVATE -Wall -Wextra -Wpedantic)
  endif()

  add_test(NAME vectorai.binary.boundary COMMAND vectorai_boundary_tests)

  add_executable(vectorai_fitting_tests cpp/tests/fitting_tests.cpp)
  target_link_libraries(vectorai_fitting_tests PRIVATE VectorAI::core)
  target_compile_features(vectorai_fitting_tests PRIVATE cxx_std_17)
  set_target_properties(vectorai_fitting_tests PROPERTIES CXX_EXTENSIONS OFF)

  if(MSVC)
    target_compile_options(vectorai_fitting_tests PRIVATE /W4 /permissive-)
  else()
    target_compile_options(vectorai_fitting_tests PRIVATE -Wall -Wextra -Wpedantic)
  endif()

  add_test(NAME vectorai.binary.fitting COMMAND vectorai_fitting_tests)

  add_executable(vectorai_model_selection_tests cpp/tests/model_selection_tests.cpp)
  target_link_libraries(vectorai_model_selection_tests PRIVATE VectorAI::core)
  target_compile_features(vectorai_model_selection_tests PRIVATE cxx_std_17)
  set_target_properties(vectorai_model_selection_tests PROPERTIES CXX_EXTENSIONS OFF)

  if(MSVC)
    target_compile_options(vectorai_model_selection_tests PRIVATE /W4 /permissive-)
  else()
    target_compile_options(vectorai_model_selection_tests PRIVATE -Wall -Wextra -Wpedantic)
  endif()

  add_test(NAME vectorai.binary.model_selection COMMAND vectorai_model_selection_tests)

  add_executable(vectorai_svg_tests cpp/tests/svg_tests.cpp)
  target_link_libraries(vectorai_svg_tests PRIVATE VectorAI::core)
  target_compile_features(vectorai_svg_tests PRIVATE cxx_std_17)
  set_target_properties(vectorai_svg_tests PROPERTIES CXX_EXTENSIONS OFF)

  if(MSVC)
    target_compile_options(vectorai_svg_tests PRIVATE /W4 /permissive-)
  else()
    target_compile_options(vectorai_svg_tests PRIVATE -Wall -Wextra -Wpedantic)
  endif()

  add_test(NAME vectorai.binary.svg COMMAND vectorai_svg_tests)

  add_executable(vectorai_pipeline_stability_tests
    cpp/tests/pipeline_stability_tests.cpp
  )
  target_link_libraries(vectorai_pipeline_stability_tests PRIVATE VectorAI::core)
  target_compile_features(vectorai_pipeline_stability_tests PRIVATE cxx_std_17)
  set_target_properties(vectorai_pipeline_stability_tests PROPERTIES CXX_EXTENSIONS OFF)

  if(MSVC)
    target_compile_options(vectorai_pipeline_stability_tests PRIVATE /W4 /permissive-)
  else()
    target_compile_options(vectorai_pipeline_stability_tests PRIVATE -Wall -Wextra -Wpedantic)
  endif()

  add_test(NAME vectorai.binary.pipeline_stability COMMAND vectorai_pipeline_stability_tests)
endif()
