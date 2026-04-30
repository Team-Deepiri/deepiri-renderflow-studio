#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod commands;

#[tauri::command]
fn app_mode(ai_enabled: bool) -> String {
    if ai_enabled {
        "ai-assist".to_string()
    } else {
        "manual-only".to_string()
    }
}

fn main() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![
            app_mode,
            commands::orchestrator::orchestrator_health,
            commands::orchestrator::submit_ai_job,
            commands::orchestrator::get_ai_job,
            commands::orchestrator::orchestrator_list_projects,
            commands::engine::timeline_resolve_active,
            commands::engine::render_graph_schedule,
            commands::engine::vulkan_discover,
            commands::engine::timeline_frame_to_time,
            commands::engine::timeline_time_to_sample,
            commands::engine::clip_span_intersects,
            commands::audio::start_audio_recording,
            commands::audio::stop_audio_recording,
            commands::audio::check_microphone,
            commands::audio::generate_tts,
            commands::audio::list_tts_voices,
        ])
        .run(tauri::generate_context!())
        .expect("failed to run deepiri-renderflow-desktop");
}
