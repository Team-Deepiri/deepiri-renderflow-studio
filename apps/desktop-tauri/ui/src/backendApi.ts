import { invoke } from "@tauri-apps/api/core";

export function orchestratorHealth(): Promise<unknown> {
  return invoke("orchestrator_health", { baseUrl: null });
}

export function orchestratorListProjects(): Promise<unknown> {
  return invoke("orchestrator_list_projects", { baseUrl: null });
}

export function vulkanDiscover(): Promise<unknown> {
  return invoke("vulkan_discover", {});
}

export function timelineResolveActive(payload: unknown): Promise<unknown> {
  return invoke("timeline_resolve_active", { payload });
}

export function submitAiJob(prompt: string): Promise<{ job_id: string; status: string }> {
  return invoke("submit_ai_job", {
    projectId: "renderflow-local-project",
    mode: "scene-generation",
    prompt,
    baseUrl: null,
  });
}

export function getAiJob(jobId: string): Promise<unknown> {
  return invoke("get_ai_job", { jobId, baseUrl: null });
}

export async function probeMedia(path: string): Promise<string> {
  const base = "http://127.0.0.1:8080";
  const res = await fetch(`${base}/v1/media/probe`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path }),
  });
  return res.text();
}
