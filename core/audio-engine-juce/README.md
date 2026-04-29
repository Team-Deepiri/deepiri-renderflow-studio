# audio-engine-juce

JUCE-backed audio engine boundary for Renderflow Studio.

Planned responsibilities:
- transport sync with timeline playhead,
- bus routing + FX chain graph,
- monitor and export paths,
- plugin hosting integration layer.

Implementation lands in native C++ module with Rust FFI bridge.
