#pragma once

#include <cstdint>

namespace renderflow::audio {

/// Transport state mirrored from the timeline (stub until JUCE graph is wired).
enum class TransportState : std::uint8_t { Stopped, Playing };

struct EngineConfig {
  double sample_rate = 48000.0;
  std::uint32_t buffer_frames = 512;
};

class AudioEngine {
 public:
  explicit AudioEngine(EngineConfig cfg);
  void prepare();
  void set_transport(TransportState s);
  [[nodiscard]] TransportState transport() const;

 private:
  EngineConfig cfg_;
  TransportState transport_{TransportState::Stopped};
};

}  // namespace renderflow::audio
