use serde_json::Value;
use timeline_engine_rs::sequence::Sequence;

#[tauri::command]
pub fn timeline_resolve_active(payload: Value) -> Result<Value, String> {
    let seq_val = payload
        .get("sequence")
        .cloned()
        .ok_or_else(|| "missing sequence".to_string())?;
    let playhead = payload
        .get("playhead_tick")
        .and_then(|v| v.as_i64())
        .ok_or_else(|| "missing playhead_tick".to_string())?;
    let seq: Sequence = serde_json::from_value(seq_val).map_err(|e| e.to_string())?;
    let active = seq.active_clips_at(playhead);
    let clips: Vec<Value> = active
        .iter()
        .map(|c| serde_json::to_value(*c).map_err(|e| e.to_string()))
        .collect::<Result<_, _>>()?;
    Ok(serde_json::json!({
        "active_clip_ids": active.iter().map(|c| c.id).collect::<Vec<_>>(),
        "active_clips": clips,
    }))
}

#[tauri::command]
pub fn render_graph_schedule(graph: Value) -> Result<Value, String> {
    let g: render_engine_vulkan::RenderGraph =
        serde_json::from_value(graph).map_err(|e| e.to_string())?;
    let order = render_engine_vulkan::graph_schedule::schedule(&g).map_err(|e| e.to_string())?;
    let ids: Vec<String> = order.iter().map(|p| p.id.clone()).collect();
    Ok(serde_json::json!({ "pass_order": ids }))
}

#[tauri::command]
pub fn vulkan_discover() -> Result<Value, String> {
    let d = render_engine_vulkan::loader::discover().map_err(|e| e.to_string())?;
    serde_json::to_value(d).map_err(|e| e.to_string())
}
