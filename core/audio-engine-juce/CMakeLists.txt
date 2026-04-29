cmake_minimum_required(VERSION 3.22)
project(deepiri_renderflow_audio LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Full build: point JUCE_ROOT to a JUCE checkout and add find_package(JUCE) + target_link_libraries.
# This stub compiles without JUCE for CI and documents the integration boundary.

add_library(renderflow_audio_stub STATIC
  src/audio_engine_stub.cpp
)
target_include_directories(renderflow_audio_stub PUBLIC include)
