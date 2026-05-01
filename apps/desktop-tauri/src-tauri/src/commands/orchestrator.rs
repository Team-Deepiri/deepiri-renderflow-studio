use serde::Serialize;
use serde_json::Value;

fn resolve_base(override_url: Option<String>) -> String {
    let from_arg = override_url.and_then(|s| {
        let t = s.trim().to_string();
        if t.is_empty() {
            None
        } else {
            Some(t)
        }
    });
    from_arg
        .or_else(|| std::env::var("RENDERFLOW_ORCHESTRATOR_URL").ok())
        .unwrap_or_else(|| "http://127.0.0.1:8080".to_string())
        .trim_end_matches('/')
        .to_string()
}

#[tauri::command]
pub fn orchestrator_health(base_url: Option<String>) -> Result<Value, String> {
    let url = format!("{}/health", resolve_base(base_url));
    let resp = reqwest::blocking::get(&url).map_err(|e| e.to_string())?;
    if !resp.status().is_success() {
        return Err(format!("HTTP {}", resp.status()));
    }
    resp.json().map_err(|e| e.to_string())
}

#[derive(Debug, Serialize)]
pub struct SubmitJobResult {
    pub job_id: String,
    pub status: String,
}

#[tauri::command]
pub fn submit_ai_job(
    project_id: String,
    mode: String,
    prompt: String,
    base_url: Option<String>,
) -> Result<SubmitJobResult, String> {
    let url = format!("{}/v1/jobs", resolve_base(base_url));
    let body = serde_json::json!({
        "project_id": project_id,
        "mode": mode,
        "prompt": prompt,
        "metadata": {}
    });
    let client = reqwest::blocking::Client::new();
    let resp = client
        .post(&url)
        .json(&body)
        .send()
        .map_err(|e| e.to_string())?;
    if !resp.status().is_success() {
        return Err(format!(
            "HTTP {}: {}",
            resp.status(),
            resp.text().unwrap_or_default()
        ));
    }
    let v: Value = resp.json().map_err(|e| e.to_string())?;
    Ok(SubmitJobResult {
        job_id: v["id"].as_str().unwrap_or("").to_string(),
        status: v["status"].as_str().unwrap_or("").to_string(),
    })
}

#[tauri::command]
pub fn get_ai_job(job_id: String, base_url: Option<String>) -> Result<Value, String> {
    let url = format!("{}/v1/jobs/{}", resolve_base(base_url), job_id);
    let resp = reqwest::blocking::get(&url).map_err(|e| e.to_string())?;
    if !resp.status().is_success() {
        return Err(format!("HTTP {}", resp.status()));
    }
    resp.json().map_err(|e| e.to_string())
}

#[tauri::command]
pub fn orchestrator_list_projects(base_url: Option<String>) -> Result<Value, String> {
    let url = format!("{}/v1/projects", resolve_base(base_url));
    let resp = reqwest::blocking::get(&url).map_err(|e| e.to_string())?;
    if !resp.status().is_success() {
        return Err(format!("HTTP {}", resp.status()));
    }
    resp.json().map_err(|e| e.to_string())
}

#[derive(Debug, Serialize)]
pub struct ProjectListResult {
    pub items: Vec<Value>,
    pub total: i32,
    pub page: i32,
    pub page_size: i32,
}

#[tauri::command]
pub fn orchestrator_list_projects_paginated(
    page: i32,
    page_size: i32,
    base_url: Option<String>,
) -> Result<ProjectListResult, String> {
    let url = format!(
        "{}/v1/projects?page={}&page_size={}",
        resolve_base(base_url),
        page,
        page_size
    );
    let resp = reqwest::blocking::get(&url).map_err(|e| e.to_string())?;
    if !resp.status().is_success() {
        return Err(format!("HTTP {}", resp.status()));
    }
    let v: Value = resp.json().map_err(|e| e.to_string())?;
    Ok(ProjectListResult {
        items: v["items"].as_array().cloned().unwrap_or_default(),
        total: v["total"].as_i64().unwrap_or(0) as i32,
        page: v["page"].as_i64().unwrap_or(1) as i32,
        page_size: v["page_size"].as_i64().unwrap_or(20) as i32,
    })
}

#[tauri::command]
pub fn orchestrator_create_project(
    name: String,
    fps_num: i32,
    fps_den: i32,
    base_url: Option<String>,
) -> Result<Value, String> {
    let url = format!("{}/v1/projects", resolve_base(base_url));
    let body = serde_json::json!({
        "name": name,
        "fps_num": fps_num,
        "fps_den": fps_den,
    });
    let client = reqwest::blocking::Client::new();
    let resp = client
        .post(&url)
        .json(&body)
        .send()
        .map_err(|e| e.to_string())?;
    if !resp.status().is_success() {
        return Err(format!("HTTP {}", resp.status()));
    }
    resp.json().map_err(|e| e.to_string())
}

#[tauri::command]
pub fn orchestrator_get_project(
    project_id: String,
    base_url: Option<String>,
) -> Result<Value, String> {
    let url = format!("{}/v1/projects/{}", resolve_base(base_url), project_id);
    let resp = reqwest::blocking::get(&url).map_err(|e| e.to_string())?;
    if !resp.status().is_success() {
        return Err(format!("HTTP {}", resp.status()));
    }
    resp.json().map_err(|e| e.to_string())
}

#[tauri::command]
pub fn orchestrator_delete_project(
    project_id: String,
    base_url: Option<String>,
) -> Result<Value, String> {
    let url = format!("{}/v1/projects/{}", resolve_base(base_url), project_id);
    let client = reqwest::blocking::Client::new();
    let resp = client.delete(&url).send().map_err(|e| e.to_string())?;
    if !resp.status().is_success() {
        return Err(format!("HTTP {}", resp.status()));
    }
    resp.json().map_err(|e| e.to_string())
}

#[tauri::command]
pub fn orchestrator_list_sequences(
    project_id: String,
    base_url: Option<String>,
) -> Result<Value, String> {
    let url = format!(
        "{}/v1/projects/{}/sequences",
        resolve_base(base_url),
        project_id
    );
    let resp = reqwest::blocking::get(&url).map_err(|e| e.to_string())?;
    if !resp.status().is_success() {
        return Err(format!("HTTP {}", resp.status()));
    }
    resp.json().map_err(|e| e.to_string())
}

#[tauri::command]
pub fn orchestrator_create_sequence(
    project_id: String,
    name: String,
    resolution_w: i32,
    resolution_h: i32,
    base_url: Option<String>,
) -> Result<Value, String> {
    let url = format!(
        "{}/v1/projects/{}/sequences",
        resolve_base(base_url),
        project_id
    );
    let body = serde_json::json!({
        "name": name,
        "resolution_w": resolution_w,
        "resolution_h": resolution_h,
    });
    let client = reqwest::blocking::Client::new();
    let resp = client
        .post(&url)
        .json(&body)
        .send()
        .map_err(|e| e.to_string())?;
    if !resp.status().is_success() {
        return Err(format!("HTTP {}", resp.status()));
    }
    resp.json().map_err(|e| e.to_string())
}

#[tauri::command]
pub fn orchestrator_get_capabilities(base_url: Option<String>) -> Result<Value, String> {
    let url = format!("{}/v1/capabilities", resolve_base(base_url));
    let resp = reqwest::blocking::get(&url).map_err(|e| e.to_string())?;
    if !resp.status().is_success() {
        return Err(format!("HTTP {}", resp.status()));
    }
    resp.json().map_err(|e| e.to_string())
}
