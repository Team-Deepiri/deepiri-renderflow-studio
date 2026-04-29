use serde::{Deserialize, Serialize};

use crate::{ClipSpan, TimelineClock};

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub enum TrackKind {
    Video,
    Audio,
    Subtitle,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Track {
    pub id: u64,
    pub kind: TrackKind,
    pub lane_index: i32,
    pub name: String,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize)]
pub struct Clip {
    pub id: u64,
    pub track_id: u64,
    pub asset_id: u64,
    pub span: ClipSpan,
    pub src_in_tick: i64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Sequence {
    pub tracks: Vec<Track>,
    pub clips: Vec<Clip>,
}

impl Sequence {
    pub fn active_clips_at(&self, playhead_tick: i64) -> Vec<&Clip> {
        let mut v: Vec<&Clip> = self
            .clips
            .iter()
            .filter(|c| c.span.is_active(playhead_tick))
            .collect();
        v.sort_by_key(|c| {
            let lane = self
                .tracks
                .iter()
                .find(|t| t.id == c.track_id)
                .map(|t| t.lane_index)
                .unwrap_or(0);
            (lane, c.span.in_tick)
        });
        v
    }

    pub fn frame_at(&self, clock: &TimelineClock, frame_index: i64) -> i64 {
        let t = clock.frame_to_time(frame_index);
        let ticks_per_sec = clock.ticks_per_second as i64;
        (t.to_seconds() * ticks_per_sec as f64).round() as i64
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn resolves_active_ordered_by_lane() {
        let seq = Sequence {
            tracks: vec![
                Track {
                    id: 1,
                    kind: TrackKind::Video,
                    lane_index: 1,
                    name: "V1".into(),
                },
                Track {
                    id: 2,
                    kind: TrackKind::Video,
                    lane_index: 0,
                    name: "V2".into(),
                },
            ],
            clips: vec![
                Clip {
                    id: 10,
                    track_id: 1,
                    asset_id: 100,
                    span: ClipSpan {
                        in_tick: 0,
                        out_tick: 100,
                    },
                    src_in_tick: 0,
                },
                Clip {
                    id: 11,
                    track_id: 2,
                    asset_id: 101,
                    span: ClipSpan {
                        in_tick: 0,
                        out_tick: 100,
                    },
                    src_in_tick: 0,
                },
            ],
        };
        let act = seq.active_clips_at(50);
        assert_eq!(act.len(), 2);
        assert_eq!(act[0].track_id, 2);
        assert_eq!(act[1].track_id, 1);
    }
}
