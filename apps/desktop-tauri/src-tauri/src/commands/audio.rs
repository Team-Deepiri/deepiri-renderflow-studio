use serde_json::Value;
use std::process::Command;

#[tauri::command]
pub fn check_microphone() -> Result<Value, String> {
    let output = Command::new("powershell")
        .args(["-Command", "Get-WmiObject -Class Win32_SoundDevice"])
        .output()
        .map_err(|e| e.to_string())?;

    let available = output.status.success();
    Ok(serde_json::json!({
        "available": available,
        "ok": true
    }))
}

#[tauri::command]
pub fn start_audio_recording(output_path: String) -> Result<Value, String> {
    let output = Command::new("powershell")
        .args([
            "-Command",
            &format!(
                "ffmpeg -y -f dshow -i audio=virtual-audio-capturer -t 60 -ar 48000 -ac 1 -acodec pcm_s16le {}",
                output_path
            ),
        ])
        .output()
        .map_err(|e| e.to_string())?;

    if !output.status.success() {
        return Err(String::from_utf8_lossy(&output.stderr).to_string());
    }

    Ok(serde_json::json!({
        "ok": true,
        "recording": true,
        "output": output_path
    }))
}

#[tauri::command]
pub fn stop_audio_recording() -> Result<Value, String> {
    Ok(serde_json::json!({
        "ok": true,
        "recording": false
    }))
}

#[tauri::command]
pub fn generate_tts(text: String, output_path: String, voice: Option<String>) -> Result<Value, String> {
    let voice = voice.unwrap_or_else(|| "en-US-AriaNeural".to_string());

    let output = Command::new("edge-tts")
        .args([
            "--voice",
            &voice,
            "--write-media",
            &output_path,
            "--text",
            &text,
        ])
        .output()
        .map_err(|e| e.to_string())?;

    if !output.status.success() {
        return Err(String::from_utf8_lossy(&output.stderr).to_string());
    }

    Ok(serde_json::json!({
        "ok": true,
        "output": output_path,
        "engine": "edge-tts",
        "voice": voice
    }))
}

#[tauri::command]
pub fn list_tts_voices() -> Result<Value, String> {
    Ok(serde_json::json!({
        "voices": {
            "en-US-AriaNeural": {"name": "Aria", "gender": "Female"},
            "en-US-GuyNeural": {"name": "Guy", "gender": "Male"},
            "en-US-JennyNeural": {"name": "Jenny", "gender": "Female"},
            "en-GB-SoniaNeural": {"name": "Sonia", "gender": "Female"}
        }
    }))
}