use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
pub enum ContainerFormat {
    Mp4,
    Mov,
    WebM,
    Exr,
    Png,
    Jpeg,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
pub enum VideoCodec {
    H264,
    H265,
    Av1,
    Prores422,
    Prores4444,
    Vp9,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
pub enum AudioCodec {
    Aac,
    Pcm,
    Opus,
    Mp3,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RenderPreset {
    pub name: String,
    pub container: ContainerFormat,
    pub video_codec: VideoCodec,
    pub audio_codec: AudioCodec,
    pub video_bitrate_kbps: Option<u32>,
    pub audio_bitrate_kbps: Option<u32>,
    pub resolution_w: u32,
    pub resolution_h: u32,
    pub fps_num: u32,
    pub fps_den: u32,
}

impl RenderPreset {
    pub fn h264_1080p() -> Self {
        Self {
            name: "h264_1080p".into(),
            container: ContainerFormat::Mp4,
            video_codec: VideoCodec::H264,
            audio_codec: AudioCodec::Aac,
            video_bitrate_kbps: Some(8000),
            audio_bitrate_kbps: Some(128),
            resolution_w: 1920,
            resolution_h: 1080,
            fps_num: 24,
            fps_den: 1,
        }
    }

    pub fn prores_422() -> Self {
        Self {
            name: "prores_422".into(),
            container: ContainerFormat::Mov,
            video_codec: VideoCodec::Prores422,
            audio_codec: AudioCodec::Pcm,
            video_bitrate_kbps: None,
            audio_bitrate_kbps: None,
            resolution_w: 1920,
            resolution_h: 1080,
            fps_num: 24,
            fps_den: 1,
        }
    }

    pub fn web_4k() -> Self {
        Self {
            name: "web_4k".into(),
            container: ContainerFormat::WebM,
            video_codec: VideoCodec::Vp9,
            audio_codec: AudioCodec::Opus,
            video_bitrate_kbps: Some(20000),
            audio_bitrate_kbps: Some(128),
            resolution_w: 3840,
            resolution_h: 2160,
            fps_num: 30,
            fps_den: 1,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub enum RenderJobStatus {
    Queued,
    Preparing,
    Rendering,
    Encoding,
    Completed,
    Failed,
    Cancelled,
}

impl Default for RenderJobStatus {
    fn default() -> Self {
        Self::Queued
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RenderJob {
    pub id: String,
    pub project_id: String,
    pub sequence_id: Option<String>,
    pub preset_name: String,
    pub status: RenderJobStatus,
    pub output_uri: Option<String>,
    pub progress: f32,
    pub frame_count: u32,
    pub frames_rendered: u32,
    pub error_message: Option<String>,
}

impl RenderJob {
    pub fn new(project_id: String, sequence_id: Option<String>, preset: &RenderPreset) -> Self {
        Self {
            id: uuid::Uuid::new_v4().to_string(),
            project_id,
            sequence_id,
            preset_name: preset.name.clone(),
            status: RenderJobStatus::Queued,
            output_uri: None,
            progress: 0.0,
            frame_count: 0,
            frames_rendered: 0,
            error_message: None,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn preset_creation() {
        let p = RenderPreset::h264_1080p();
        assert_eq!(p.resolution_w, 1920);
        assert_eq!(p.resolution_h, 1080);
    }
}