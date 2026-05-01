use serde_json::Value;
use timeline_engine_rs::sequence::Sequence;
use timeline_engine_rs::{
    Clip, ClipSpan, Effect, Keyframe, Marker, MarkerType, RationalTime, TimeRange, TimelineClock,
    Track, TrackType, Transport, TransportState,
};

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

#[tauri::command]
pub fn timeline_frame_to_time(payload: Value) -> Result<Value, String> {
    let fps_num = payload
        .get("fps_num")
        .and_then(|v| v.as_u64())
        .ok_or("missing fps_num") as u32;
    let fps_den = payload
        .get("fps_den")
        .and_then(|v| v.as_u64())
        .ok_or("missing fps_den") as u32;
    let frame = payload
        .get("frame_index")
        .and_then(|v| v.as_i64())
        .ok_or("missing frame_index")?;
    let clock = TimelineClock::new(fps_num, fps_den).map_err(|e| e.to_string())?;
    let time = clock.frame_to_time(frame);
    Ok(serde_json::json!({
        "num": time.num,
        "den": time.den,
        "seconds": time.to_seconds()
    }))
}

#[tauri::command]
pub fn timeline_time_to_sample(payload: Value) -> Result<Value, String> {
    let fps_num = payload
        .get("fps_num")
        .and_then(|v| v.as_u64())
        .ok_or("missing fps_num") as u32;
    let fps_den = payload
        .get("fps_den")
        .and_then(|v| v.as_u64())
        .ok_or("missing fps_den") as u32;
    let sample_rate = payload
        .get("sample_rate")
        .and_then(|v| v.as_u64())
        .ok_or("missing sample_rate") as u32;
    let num = payload
        .get("num")
        .and_then(|v| v.as_i64())
        .ok_or("missing num")?;
    let den = payload
        .get("den")
        .and_then(|v| v.as_i64())
        .ok_or("missing den")?;
    let clock = TimelineClock::new(fps_num, fps_den).map_err(|e| e.to_string())?;
    let time = RationalTime { num, den };
    let sample = clock.time_to_sample_index(time, sample_rate);
    Ok(serde_json::json!({ "sample_index": sample }))
}

#[tauri::command]
pub fn clip_span_intersects(a: Value, b: Value) -> Result<bool, String> {
    let span_a: ClipSpan = serde_json::from_value(a).map_err(|e| e.to_string())?;
    let span_b: ClipSpan = serde_json::from_value(b).map_err(|e| e.to_string())?;
    let intersects = !(span_a.out_tick <= span_b.in_tick || span_a.in_tick >= span_b.out_tick);
    Ok(intersects)
}

#[tauri::command]
pub fn create_track(track_type: String, lane_index: i32, name: String) -> Result<Value, String> {
    let kind = match track_type.as_str() {
        "video" => TrackType::Video,
        "audio" => TrackType::Audio,
        "caption" => TrackType::Caption,
        "subtitle" => TrackType::Subtitle,
        "effect" => TrackType::Effect,
        "marker" => TrackType::Marker,
        _ => TrackType::Video,
    };
    let track = Track {
        id: uuid::Uuid::new_v4().to_string(),
        track_type: kind,
        lane_index,
        name: name.clone(),
        muted: false,
        locked: false,
        solo: false,
        height: 60,
        color: "#4A90D9".to_string(),
    };
    serde_json::to_value(track).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn timeline_range_contains(range: Value, tick: i64) -> Result<bool, String> {
    let r: TimeRange = serde_json::from_value(range).map_err(|e| e.to_string())?;
    Ok(r.contains_tick(tick))
}

#[tauri::command]
pub fn timeline_ranges_overlap(a: Value, b: Value) -> Result<bool, String> {
    let r1: TimeRange = serde_json::from_value(a).map_err(|e| e.to_string())?;
    let r2: TimeRange = serde_json::from_value(b).map_err(|e| e.to_string())?;
    Ok(r1.overlaps(&r2))
}

#[tauri::command]
pub fn create_marker(time_tick: i64, label: String, marker_type: String) -> Result<Value, String> {
    let mt = match marker_type.as_str() {
        "chapter" => MarkerType::Chapter,
        "cue" => MarkerType::Cue,
        "weblink" => MarkerType::WebLink,
        "note" => MarkerType::Note,
        "flag" => MarkerType::Flag,
        _ => MarkerType::Note,
    };
    let marker = Marker {
        id: uuid::Uuid::new_v4().to_string(),
        time_tick,
        label,
        color: "#FFD700".to_string(),
        marker_type: mt,
    };
    serde_json::to_value(marker).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn evaluate_effect(effect: Value, tick: i64) -> Result<Value, String> {
    let eff: Effect = serde_json::from_value(effect).map_err(|e| e.to_string())?;
    let evaluated = eff.evaluate(tick);
    serde_json::to_value(evaluated).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn transport_seek(transport: Value, tick: i64) -> Result<Value, String> {
    let mut t: Transport = serde_json::from_value(transport).map_err(|e| e.to_string())?;
    t.seek(tick);
    serde_json::to_value(t).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn transport_play(transport: Value) -> Result<Value, String> {
    let mut t: Transport = serde_json::from_value(transport).map_err(|e| e.to_string())?;
    t.play();
    serde_json::to_value(t).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn transport_pause(transport: Value) -> Result<Value, String> {
    let mut t: Transport = serde_json::from_value(transport).map_err(|e| e.to_string())?;
    t.pause();
    serde_json::to_value(t).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn transport_stop(transport: Value) -> Result<Value, String> {
    let mut t: Transport = serde_json::from_value(transport).map_err(|e| e.to_string())?;
    t.stop();
    serde_json::to_value(t).map_err(|e| e.to_string())
}
