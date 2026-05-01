use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
pub enum ContainerFormat {
    Mp4,
    Mov,
    WebM,
    Exr,
    Png,
    Jpeg,
    Tiff,
    Dpx,
    ProRes,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
pub enum VideoCodec {
    H264,
    H265,
    Av1,
    Prores422,
    Prores4444,
    Vp9,
    DnxHD,
    CineForm,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
pub enum AudioCodec {
    Aac,
    Pcm,
    Opus,
    Mp3,
    Flac,
    Alac,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
pub enum ColorSpace {
    Srgb,
    Rec709,
    Rec2020,
    P3D65,
    Linear,
    Log,
}

impl Default for ColorSpace {
    fn default() -> Self {
        Self::Rec709
    }
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
pub enum Bitdepth {
    Bit8,
    Bit10,
    Bit12,
    Bit16,
    Bit16Float,
    Bit32Float,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RenderPreset {
    pub id: String,
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
    pub color_space: ColorSpace,
    pub bitdepth: Bitdepth,
    pub hdr: bool,
    pub is_preset: bool,
    pub is_default: bool,
}

impl RenderPreset {
    pub fn h264_1080p() -> Self {
        Self {
            id: uuid::Uuid::new_v4().to_string(),
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
            color_space: ColorSpace::Rec709,
            bitdepth: Bitdepth::Bit8,
            hdr: false,
            is_preset: true,
            is_default: false,
        }
    }

    pub fn prores_422() -> Self {
        Self {
            id: uuid::Uuid::new_v4().to_string(),
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
            color_space: ColorSpace::Rec709,
            bitdepth: Bitdepth::Bit10,
            hdr: false,
            is_preset: true,
            is_default: false,
        }
    }

    pub fn web_4k() -> Self {
        Self {
            id: uuid::Uuid::new_v4().to_string(),
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
            color_space: ColorSpace::Rec709,
            bitdepth: Bitdepth::Bit8,
            hdr: false,
            is_preset: true,
            is_default: false,
        }
    }

    pub fn hdr_4k() -> Self {
        Self {
            id: uuid::Uuid::new_v4().to_string(),
            name: "hdr_4k".into(),
            container: ContainerFormat::Mp4,
            video_codec: VideoCodec::H265,
            audio_codec: AudioCodec::Aac,
            video_bitrate_kbps: Some(25000),
            audio_bitrate_kbps: Some(256),
            resolution_w: 3840,
            resolution_h: 2160,
            fps_num: 60,
            fps_den: 1,
            color_space: ColorSpace::Rec2020,
            bitdepth: Bitdepth::Bit10,
            hdr: true,
            is_preset: true,
            is_default: false,
        }
    }

    pub fn exr_sequence() -> Self {
        Self {
            id: uuid::Uuid::new_v4().to_string(),
            name: "exr_sequence".into(),
            container: ContainerFormat::Exr,
            video_codec: VideoCodec::Prores4444,
            audio_codec: AudioCodec::Pcm,
            video_bitrate_kbps: None,
            audio_bitrate_kbps: None,
            resolution_w: 1920,
            resolution_h: 1080,
            fps_num: 24,
            fps_den: 1,
            color_space: ColorSpace::Linear,
            bitdepth: Bitdepth::Bit16Float,
            hdr: true,
            is_preset: true,
            is_default: false,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RenderSettings {
    pub preset: RenderPreset,
    pub start_frame: i64,
    pub end_frame: i64,
    pub output_pattern: String,
    pub audio_enabled: bool,
    pub video_enabled: bool,
    pub multipass: bool,
    pub gpu_accelerated: bool,
    pub threads: u32,
    pub tile_size: Option<u32>,
}

impl Default for RenderSettings {
    fn default() -> Self {
        Self {
            preset: RenderPreset::h264_1080p(),
            start_frame: 0,
            end_frame: -1,
            output_pattern: "output_{:04d}.{:ext}".into(),
            audio_enabled: true,
            video_enabled: true,
            multipass: true,
            gpu_accelerated: true,
            threads: 0,
            tile_size: None,
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
