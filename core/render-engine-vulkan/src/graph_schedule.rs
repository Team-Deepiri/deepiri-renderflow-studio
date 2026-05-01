use serde::{Deserialize, Serialize};
use std::collections::{HashMap, HashSet, VecDeque};
use thiserror::Error;

use crate::{RenderGraph, RenderPass};

#[derive(Debug, Error)]
pub enum ScheduleError {
    #[error("unknown pass dependency: {0}")]
    UnknownDependency(String),
    #[error("cycle in render graph")]
    Cycle,
    #[error("unsupported pass type")]
    UnsupportedPassType,
}

pub fn schedule(graph: &RenderGraph) -> Result<Vec<&RenderPass>, ScheduleError> {
    let id_to_pass: HashMap<&str, &RenderPass> =
        graph.passes.iter().map(|p| (p.id.as_str(), p)).collect();
    let mut indegree: HashMap<&str, usize> = HashMap::new();
    for p in &graph.passes {
        indegree.insert(p.id.as_str(), p.depends_on.len());
        for dep in &p.depends_on {
            if !id_to_pass.contains_key(dep.as_str()) {
                return Err(ScheduleError::UnknownDependency(dep.clone()));
            }
        }
    }
    let mut q: VecDeque<&str> = indegree
        .iter()
        .filter(|(_, &d)| d == 0)
        .map(|(&id, _)| id)
        .collect();
    let mut out: Vec<&RenderPass> = Vec::new();
    while let Some(id) = q.pop_front() {
        out.push(id_to_pass[id]);
        for p in &graph.passes {
            if p.depends_on.iter().any(|d| d == id) {
                let e = indegree.get_mut(p.id.as_str()).unwrap();
                *e -= 1;
                if *e == 0 {
                    q.push_back(p.id.as_str());
                }
            }
        }
    }
    if out.len() != graph.passes.len() {
        return Err(ScheduleError::Cycle);
    }
    Ok(out)
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FrameGraph {
    pub name: String,
    pub passes: Vec<FramePass>,
    pub resources: Vec<FrameResource>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FramePass {
    pub id: String,
    pub pass_type: FramePassType,
    pub shader: Option<String>,
    pub reads: Vec<String>,
    pub writes: Vec<String>,
    pub clears: Vec<ClearValue>,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
pub enum FramePassType {
    Render,
    Compute,
    Copy,
    Present,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FrameResource {
    pub id: String,
    pub resource_type: FrameResourceType,
    pub format: Option<String>,
    pub dimensions: Option<(u32, u32)>,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
pub enum FrameResourceType {
    Texture,
    Buffer,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ClearValue {
    pub attachment: u32,
    pub clear_type: ClearType,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum ClearType {
    Color([f32; 4]),
    DepthStencil(f32, u32),
}

impl FrameGraph {
    pub fn new(name: String) -> Self {
        Self {
            name,
            passes: Vec::new(),
            resources: Vec::new(),
        }
    }

    pub fn add_resource(&mut self, id: String, resource_type: FrameResourceType) -> &mut Self {
        self.resources.push(FrameResource {
            id,
            resource_type,
            format: None,
            dimensions: None,
        });
        self
    }

    pub fn add_pass(&mut self, mut pass: FramePass) -> &mut Self {
        pass.id = format!("pass_{}", self.passes.len());
        self.passes.push(pass);
        self
    }

    pub fn compile(&self) -> Result<FrameGraphCompiled, ScheduleError> {
        let id_to_pass: HashMap<&str, &FramePass> =
            self.passes.iter().map(|p| (p.id.as_str(), p)).collect();

        let mut all_writes: HashSet<&str> = HashSet::new();
        let mut indegree: HashMap<&str, usize> = HashMap::new();

        for pass in &self.passes {
            let reads_in_order = pass
                .reads
                .iter()
                .filter(|r| all_writes.contains(r.as_str()))
                .count();
            indegree.insert(pass.id.as_str(), pass.reads.len() - reads_in_order);

            for write in &pass.writes {
                all_writes.insert(write.as_str());
            }
        }

        let mut q: VecDeque<&str> = indegree
            .iter()
            .filter(|(_, &d)| d == 0)
            .map(|(&id, _)| id)
            .collect();

        let mut out: Vec<String> = Vec::new();
        while let Some(id) = q.pop_front() {
            out.push(id.to_string());
            for p in &self.passes {
                if p.reads.iter().any(|r| r == id) {
                    if let Some(d) = indegree.get_mut(p.id.as_str()) {
                        *d -= 1;
                        if *d == 0 {
                            q.push_back(p.id.as_str());
                        }
                    }
                }
            }
        }

        Ok(FrameGraphCompiled { pass_order: out })
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FrameGraphCompiled {
    pub pass_order: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ComputePass {
    pub id: String,
    pub shader: String,
    pub local_size: (u32, u32, u32),
    pub dispatch_count: (u32, u32, u32),
    pub buffers: Vec<ComputeBufferBinding>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ComputeBufferBinding {
    pub binding: u32,
    pub buffer_id: String,
    pub access: ComputeAccess,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
pub enum ComputeAccess {
    Read,
    Write,
    ReadWrite,
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::RenderGraph;

    #[test]
    fn baseline_order() {
        let g = RenderGraph::baseline_preview_graph();
        let ord = schedule(&g).unwrap();
        assert_eq!(ord[0].id, "decode");
        assert_eq!(ord.last().unwrap().id, "present");
    }
}
