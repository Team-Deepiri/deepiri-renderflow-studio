use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use thiserror::Error;

pub mod sequence;

pub const DEFAULT_TICKS_PER_SECOND: u64 = 48_000;
pub const DEFAULT_AUDIO_SAMPLE_RATE: u32 = 48_000;

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
pub struct RationalTime {
    pub num: i64,
    pub den: i64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TimeRange {
    pub start_tick: i64,
    pub end_tick: i64,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
pub enum TrackType {
    Video,
    Audio,
    Caption,
    Subtitle,
    Effect,
    Marker,
}

impl RationalTime {
    pub fn to_seconds(self) -> f64 {
        if self.den == 0 {
            0.0
        } else {
            self.num as f64 / self.den as f64
        }
    }

    pub fn zero() -> Self {
        Self { num: 0, den: 1 }
    }

    pub fn as_ticks(self, ticks_per_second: i64) -> i64 {
        (self.to_seconds() * ticks_per_second as f64).round() as i64
    }

    pub fn from_seconds(seconds: f64) -> Self {
        Self {
            num: (seconds * 1_000_000.0).round() as i64,
            den: 1_000_000,
        }
    }

    pub fn from_ticks(ticks: i64, ticks_per_second: i64) -> Self {
        Self {
            num: ticks,
            den: ticks_per_second,
        }
    }
}

impl TimeRange {
    pub fn new(start_tick: i64, end_tick: i64) -> Self {
        Self {
            start_tick,
            end_tick,
        }
    }

    pub fn duration_ticks(&self) -> i64 {
        self.end_tick - self.start_tick
    }

    pub fn contains_tick(&self, tick: i64) -> bool {
        tick >= self.start_tick && tick < self.end_tick
    }

    pub fn overlaps(&self, other: &TimeRange) -> bool {
        self.start_tick < other.end_tick && other.start_tick < self.end_tick
    }

    pub fn intersection(&self, other: &TimeRange) -> Option<TimeRange> {
        if self.overlaps(other) {
            Some(TimeRange::new(
                self.start_tick.max(other.start_tick),
                self.end_tick.min(other.end_tick),
            ))
        } else {
            None
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Track {
    pub id: String,
    pub track_type: TrackType,
    pub lane_index: i32,
    pub name: String,
    pub muted: bool,
    pub locked: bool,
    pub solo: bool,
    pub height: i32,
    pub color: String,
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

#[derive(Debug, Clone, Copy, Default, Serialize, Deserialize, PartialEq, Eq)]
pub enum TransportState {
    #[default]
    Stopped,
    Playing,
    Paused,
    Scrubbing,
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
    pub fn evaluate(
        &self,
        _prev: Option<&Keyframe>,
        _next: Option<&Keyframe>,
        _interp: Interpolation,
    ) -> f64 {
        self.value
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Clip {
    pub id: String,
    pub track_id: String,
    pub asset_id: String,
    pub name: String,
    pub in_tick: i64,
    pub out_tick: i64,
    pub src_in_tick: i64,
    pub src_duration_ticks: i64,
    pub speed_ratio: f64,
    pub time_remap_enabled: bool,
    pub properties: HashMap<String, PropertyValue>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(untagged)]
pub enum PropertyValue {
    Float(f64),
    Vec2([f64; 2]),
    Vec3([f64; 3]),
    Vec4([f64; 4]),
    String(String),
    Bool(bool),
}

impl Default for Clip {
    fn default() -> Self {
        Self {
            id: String::new(),
            track_id: String::new(),
            asset_id: String::new(),
            name: String::new(),
            in_tick: 0,
            out_tick: 0,
            src_in_tick: 0,
            src_duration_ticks: 0,
            speed_ratio: 1.0,
            time_remap_enabled: false,
            properties: HashMap::new(),
        }
    }
}

impl Clip {
    pub fn duration_ticks(&self) -> i64 {
        self.out_tick - self.in_tick
    }

    pub fn effective_speed(&self) -> f64 {
        if self.time_remap_enabled {
            self.speed_ratio
        } else {
            1.0
        }
    }

    pub fn map_playhead_to_source(&self, playhead_tick: i64) -> i64 {
        let offset = playhead_tick - self.in_tick;
        let scaled = (offset as f64 / self.speed_ratio).round() as i64;
        self.src_in_tick + scaled
    }

    pub fn is_active(&self, playhead_tick: i64) -> bool {
        playhead_tick >= self.in_tick && playhead_tick < self.out_tick
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Marker {
    pub id: String,
    pub time_tick: i64,
    pub label: String,
    pub color: String,
    pub marker_type: MarkerType,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
pub enum MarkerType {
    Chapter,
    Cue,
    WebLink,
    Note,
    Flag,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Effect {
    pub id: String,
    pub effect_type: String,
    pub plugin_id: String,
    pub enabled: bool,
    pub parameters: std::collections::HashMap<String, EffectParameter>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EffectParameter {
    pub name: String,
    pub value: PropertyValue,
    pub keyframes: Vec<Keyframe>,
    pub interpolation: Interpolation,
}

impl Default for Effect {
    fn default() -> Self {
        Self {
            id: String::new(),
            effect_type: String::new(),
            plugin_id: String::new(),
            enabled: true,
            parameters: HashMap::new(),
        }
    }
}

impl Effect {
    pub fn evaluate(&self, tick: i64) -> std::collections::HashMap<String, f64> {
        let mut results = HashMap::new();
        for (name, param) in &self.parameters {
            let val = if param.keyframes.is_empty() {
                if let PropertyValue::Float(v) = param.value {
                    v
                } else {
                    0.0
                }
            } else {
                Self::interpolate_keyframes(tick, &param.keyframes, param.interpolation)
            };
            results.insert(name.clone(), val);
        }
        results
    }

    fn interpolate_keyframes(tick: i64, kfs: &[Keyframe], _interp: Interpolation) -> f64 {
        if kfs.is_empty() {
            return 0.0;
        }
        let mut prev: Option<&Keyframe> = None;
        let mut next: Option<&Keyframe> = None;
        for kf in kfs {
            if kf.tick <= tick {
                prev = Some(kf);
            } else {
                next = Some(kf);
                break;
            }
        }
        match (prev, next) {
            (Some(p), Some(n)) => {
                let t = (tick - p.tick) as f64 / (n.tick - p.tick) as f64;
                p.value + (n.value - p.value) * t
            }
            (Some(p), None) => p.value,
            (None, Some(n)) => n.value,
            _ => 0.0,
        }
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
