use serde::{Deserialize, Serialize};
use std::collections::HashMap;

pub mod export;
pub mod graph_schedule;
pub mod resources;
pub mod scene3d;

#[cfg(feature = "vulkan")]
pub mod loader;

pub use graph_schedule::schedule;

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
pub enum BlendMode {
    Normal,
    Multiply,
    Screen,
    Overlay,
    Darken,
    Lighten,
    ColorDodge,
    ColorBurn,
    SoftLight,
    HardLight,
    Difference,
    Exclusion,
}

impl Default for BlendMode {
    fn default() -> Self {
        Self::Normal
    }
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
pub enum ColorSpace {
    Srgb,
    Rec709,
    Rec2020,
    P3,
    Linear,
}

impl Default for ColorSpace {
    fn default() -> Self {
        Self::Srgb
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub enum FilterMode {
    Nearest,
    Linear,
    Bilinear,
    Trilinear,
    Anisotropic,
}

impl Default for FilterMode {
    fn default() -> Self {
        Self::Linear
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub enum AddressMode {
    Repeat,
    MirroredRepeat,
    ClampToEdge,
    ClampToBorder,
}

impl Default for AddressMode {
    fn default() -> Self {
        Self::ClampToEdge
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum RenderPassKind {
    Decode,
    ColorMgmt,
    Composite,
    UiOverlay,
    Present,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RenderPass {
    pub id: String,
    pub kind: RenderPassKind,
    pub depends_on: Vec<String>,
}

#[derive(Debug, Default, Clone, Serialize, Deserialize)]
pub struct RenderGraph {
    pub passes: Vec<RenderPass>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CompositeLayer {
    pub id: String,
    pub texture_id: String,
    pub x: i32,
    pub y: i32,
    pub width: u32,
    pub height: u32,
    pub opacity: f32,
    pub blend_mode: BlendMode,
    pub visible: bool,
}

impl Default for CompositeLayer {
    fn default() -> Self {
        Self {
            id: String::new(),
            texture_id: String::new(),
            x: 0,
            y: 0,
            width: 1920,
            height: 1080,
            opacity: 1.0,
            blend_mode: BlendMode::Normal,
            visible: true,
        }
    }
}

impl RenderGraph {
    pub fn baseline_preview_graph() -> Self {
        Self {
            passes: vec![
                RenderPass {
                    id: "decode".into(),
                    kind: RenderPassKind::Decode,
                    depends_on: vec![],
                },
                RenderPass {
                    id: "color".into(),
                    kind: RenderPassKind::ColorMgmt,
                    depends_on: vec!["decode".into()],
                },
                RenderPass {
                    id: "composite".into(),
                    kind: RenderPassKind::Composite,
                    depends_on: vec!["color".into()],
                },
                RenderPass {
                    id: "ui".into(),
                    kind: RenderPassKind::UiOverlay,
                    depends_on: vec!["composite".into()],
                },
                RenderPass {
                    id: "present".into(),
                    kind: RenderPassKind::Present,
                    depends_on: vec!["ui".into()],
                },
            ],
        }
    }
}
