use serde::{Deserialize, Serialize};

pub mod graph_schedule;

#[cfg(feature = "vulkan")]
pub mod loader;

pub use graph_schedule::schedule;

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
