# audio-engine-juce

JUCE-backed audio engine boundary for Renderflow Studio.

Planned responsibilities:
- transport sync with timeline playhead,
- bus routing + FX chain graph,
- monitor and export paths,
- plugin hosting integration layer.

Implementation lands in native C++ module with Rust FFI bridge.

## Stub build (no JUCE required)

```bash
cmake -S core/audio-engine-juce -B core/audio-engine-juce/build
cmake --build core/audio-engine-juce/build
```

Link a JUCE checkout via `JUCE_ROOT` and replace `renderflow_audio_stub` with a real `juce::AudioProcessorGraph` target when ready.
