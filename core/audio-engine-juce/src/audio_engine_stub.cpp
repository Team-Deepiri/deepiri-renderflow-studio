#include "renderflow/audio_engine.h"

namespace renderflow::audio {

AudioEngine::AudioEngine(EngineConfig cfg) : cfg_(cfg) {}

void AudioEngine::prepare() {
  // JUCE: AudioDeviceManager + AudioProcessorGraph initialization goes here.
}

void AudioEngine::set_transport(TransportState s) {
  transport_ = s;
}

TransportState AudioEngine::transport() const {
  return transport_;
}

}  // namespace renderflow::audio
