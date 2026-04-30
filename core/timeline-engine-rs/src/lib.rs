use serde::{Deserialize, Serialize};
use thiserror::Error;

pub mod sequence;

pub const DEFAULT_TICKS_PER_SECOND: u64 = 48_000;

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
pub struct RationalTime {
    pub num: i64,
    pub den: i64,
}

impl RationalTime {
    pub fn to_seconds(self) -> f64 {
        self.num as f64 / self.den as f64
    }

    pub fn zero() -> Self {
        Self { num: 0, den: 1 }
    }

    pub fn as_ticks(self, ticks_per_second: i64) -> i64 {
        (self.to_seconds() * ticks_per_second as f64).round() as i64
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TimelineClock {
    pub fps_num: u32,
    pub fps_den: u32,
    pub ticks_per_second: u64,
}

#[derive(Debug, Error)]
pub enum TimelineError {
    #[error("invalid frame rate")]
    InvalidFrameRate,
}

impl TimelineClock {
    pub fn new(fps_num: u32, fps_den: u32) -> Result<Self, TimelineError> {
        if fps_num == 0 || fps_den == 0 {
            return Err(TimelineError::InvalidFrameRate);
        }
        Ok(Self {
            fps_num,
            fps_den,
            ticks_per_second: DEFAULT_TICKS_PER_SECOND,
        })
    }

    pub fn frame_to_time(&self, frame_index: i64) -> RationalTime {
        RationalTime {
            num: frame_index * self.fps_den as i64,
            den: self.fps_num as i64,
        }
    }

    pub fn time_to_sample_index(&self, time: RationalTime, sample_rate: u32) -> i64 {
        (time.to_seconds() * sample_rate as f64).round() as i64
    }

    pub fn frames_to_ticks(&self, frames: i64) -> i64 {
        let time = self.frame_to_time(frames);
        time.as_ticks(self.ticks_per_second as i64)
    }

    pub fn tick_to_frame(&self, tick: i64) -> i64 {
        let seconds = tick as f64 / self.ticks_per_second as f64;
        let frame = seconds * self.fps_num as f64 / self.fps_den as f64;
        frame.round() as i64
    }
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
pub enum TransportState {
    Stopped,
    Playing,
    Paused,
    Scrubbing,
}

impl Default for TransportState {
    fn default() -> Self {
        Self::Stopped
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Transport {
    pub state: TransportState,
    pub playhead_tick: i64,
    pub in_tick: i64,
    pub out_tick: i64,
    pub loop_enabled: bool,
    pub loop_in_tick: i64,
    pub loop_out_tick: i64,
}

impl Default for Transport {
    fn default() -> Self {
        Self {
            state: TransportState::Stopped,
            playhead_tick: 0,
            in_tick: 0,
            out_tick: 0,
            loop_enabled: false,
            loop_in_tick: 0,
            loop_out_tick: 0,
        }
    }
}

impl Transport {
    pub fn seek(&mut self, tick: i64) {
        self.playhead_tick = tick.clamp(self.in_tick, self.out_tick.max(1));
    }

    pub fn play(&mut self) {
        if self.state != TransportState::Playing {
            self.state = TransportState::Playing;
        }
    }

    pub fn pause(&mut self) {
        self.state = TransportState::Paused;
    }

    pub fn stop(&mut self) {
        self.state = TransportState::Stopped;
        self.playhead_tick = self.in_tick;
    }

    pub fn step_forward(&mut self, frame_ticks: i64) {
        self.seek(self.playhead_tick + frame_ticks);
    }

    pub fn step_backward(&mut self, frame_ticks: i64) {
        self.seek(self.playhead_tick - frame_ticks);
    }
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
pub struct ClipSpan {
    pub in_tick: i64,
    pub out_tick: i64,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize)]
pub struct Keyframe {
    pub tick: i64,
    pub value: f64,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq)]
pub enum Interpolation {
    Linear,
    Bezier,
    Step,
}

impl ClipSpan {
    pub fn is_active(&self, playhead_tick: i64) -> bool {
        playhead_tick >= self.in_tick && playhead_tick < self.out_tick
    }
}

impl Keyframe {
    pub fn evaluate(&self, _prev: Option<&Keyframe>, _next: Option<&Keyframe>, _interp: Interpolation) -> f64 {
        self.value
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn frame_to_time_is_stable() {
        let c = TimelineClock::new(24, 1).unwrap();
        let t = c.frame_to_time(48);
        assert_eq!(t.num, 48);
        assert_eq!(t.den, 24);
    }

    #[test]
    fn sample_index_roundtrip() {
        let c = TimelineClock::new(30_000, 1_001).unwrap();
        let t = c.frame_to_time(300);
        let s = c.time_to_sample_index(t, 48_000);
        assert!(s > 0);
    }
}
