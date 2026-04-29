#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

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
        .invoke_handler(tauri::generate_handler![app_mode])
        .run(tauri::generate_context!())
        .expect("failed to run deepiri-renderflow-desktop");
}
