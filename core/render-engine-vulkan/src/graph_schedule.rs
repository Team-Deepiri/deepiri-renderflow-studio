use std::collections::{HashMap, VecDeque};
use thiserror::Error;

use crate::{RenderGraph, RenderPass};

#[derive(Debug, Error)]
pub enum ScheduleError {
    #[error("unknown pass dependency: {0}")]
    UnknownDependency(String),
    #[error("cycle in render graph")]
    Cycle,
}

/// Topological order of render passes for submission.
pub fn schedule(graph: &RenderGraph) -> Result<Vec<&RenderPass>, ScheduleError> {
    let id_to_pass: HashMap<&str, &RenderPass> = graph.passes.iter().map(|p| (p.id.as_str(), p)).collect();
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
