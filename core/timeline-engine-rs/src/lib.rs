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
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
pub struct ClipSpan {
    pub in_tick: i64,
    pub out_tick: i64,
}

impl ClipSpan {
    pub fn is_active(&self, playhead_tick: i64) -> bool {
        playhead_tick >= self.in_tick && playhead_tick < self.out_tick
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
