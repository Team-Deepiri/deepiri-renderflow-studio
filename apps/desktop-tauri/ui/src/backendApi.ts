import { invoke } from "@tauri-apps/api/core";

export const BASE = "http://127.0.0.1:8080";

export interface Project {
  id: string;
  name: string;
  fps_num: number;
  fps_den: number;
  sample_rate: number;
  created_at: string;
  updated_at: string;
}

export interface Sequence {
  id: string;
  project_id: string;
  name: string;
  start_tc: string;
  duration_ticks: number;
  resolution_w: number;
  resolution_h: number;
}

export interface Track {
  id: string;
  sequence_id: string;
  track_type: "video" | "audio" | "caption" | "subtitle" | "effect" | "marker";
  lane_index: number;
  name: string;
  muted: boolean;
  locked: boolean;
  solo: boolean;
}

export interface Clip {
  id: string;
  track_id: string;
  asset_id: string;
  name: string;
  in_tick: number;
  out_tick: number;
  src_in_tick: number;
  speed_ratio: number;
}

export interface AIJob {
  id: string;
  project_id: string;
  mode: string;
  prompt: string;
  status: string;
  stages: string[];
  result_asset_id?: string;
  metadata: {
    asset_id?: string;
    output_path?: string;
    artifact_error?: string;
    [key: string]: unknown;
  };
  created_at: string;
  updated_at: string;
}

export interface RenderJob {
  id: string;
  project_id: string;
  sequence_id?: string;
  preset: string;
  status: "queued" | "rendering" | "completed" | "failed";
  progress: number;
  output_uri?: string;
  error?: string;
}

export interface Asset {
  id: string;
  project_id: string;
  kind: string;
  uri: string;
  sha256: string;
  duration_ms: number | null;
  meta_jsonb: {
    name?: string;
    width?: number;
    height?: number;
    fps?: number;
    codec?: string;
    proxy_status?: "pending" | "ready" | "failed" | "unavailable";
    proxy_path?: string | null;
    source?: string;
    job_id?: string;
    size_bytes?: number;
    audio_codec?: string;
    sample_rate?: number;
    channels?: number;
    ai_generated?: boolean;
  };
  created_at: string;
}

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export interface Capabilities {
  gpu: {
    backend: string;
    confidence: number;
    details: Record<string, unknown>;
  };
  service: string;
}

interface MediaFrameResponse {
  ok?: boolean;
  base64?: string;
  error?: string;
}

export async function orchestratorHealth(): Promise<{ status: string }> {
  const res = await fetch(`${BASE}/health`);
  return res.json();
}

// These two call native Rust engine code — keep as invoke
export function vulkanDiscover(): Promise<unknown> {
  return invoke("vulkan_discover", {});
}

export function timelineResolveActive(payload: unknown): Promise<unknown> {
  return invoke("timeline_resolve_active", { payload });
}

export async function submitAiJob(projectId: string, prompt: string, mode = "scene"): Promise<{ job_id: string; status: string }> {
  const res = await fetch(`${BASE}/v1/jobs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ project_id: projectId, mode, prompt, metadata: {} }),
  });
  if (!res.ok) throw new Error(await res.text());
  const v = await res.json();
  return { job_id: v.id, status: v.status };
}

export async function getAiJob(jobId: string): Promise<AIJob> {
  const res = await fetch(`${BASE}/v1/jobs/${jobId}`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function acceptAiJob(jobId: string): Promise<AIJob> {
  const res = await fetch(`${BASE}/v1/jobs/${jobId}/accept`, { method: "POST" });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function submitRenderJob(
  projectId: string,
  sequenceId: string,
  preset = "h264_1080p",
): Promise<RenderJob> {
  const res = await fetch(`${BASE}/v1/projects/${projectId}/render-jobs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ sequence_id: sequenceId, preset }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getRenderJob(jobId: string): Promise<RenderJob> {
  const res = await fetch(`${BASE}/v1/render-jobs/${jobId}`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function rejectAIJob(jobId: string): Promise<AIJob> {
  const res = await fetch(`${BASE}/v1/jobs/${jobId}/reject`, { method: "POST" });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function orchestratorListProjects(): Promise<PaginatedResponse<Project>> {
  const res = await fetch(`${BASE}/v1/projects?page=1&page_size=20`);
  return res.json();
}

export async function orchestratorCreateProject(
  name: string,
  fpsNum = 24,
  fpsDen = 1,
): Promise<Project> {
  const res = await fetch(`${BASE}/v1/projects`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, fps_num: fpsNum, fps_den: fpsDen }),
  });
  return res.json();
}

export async function orchestratorGetProject(projectId: string): Promise<Project> {
  const res = await fetch(`${BASE}/v1/projects/${projectId}`);
  return res.json();
}

export async function orchestratorDeleteProject(projectId: string): Promise<{ status: string }> {
  const res = await fetch(`${BASE}/v1/projects/${projectId}`, { method: "DELETE" });
  return res.json();
}

export async function orchestratorListSequences(projectId: string): Promise<Sequence[]> {
  const res = await fetch(`${BASE}/v1/projects/${projectId}/sequences`);
  return res.json();
}

export async function orchestratorCreateSequence(
  projectId: string,
  name: string,
  resolutionW = 1920,
  resolutionH = 1080,
): Promise<Sequence> {
  const res = await fetch(`${BASE}/v1/projects/${projectId}/sequences`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, resolution_w: resolutionW, resolution_h: resolutionH }),
  });
  return res.json();
}

export async function orchestratorGetCapabilities(): Promise<Capabilities> {
  const res = await fetch(`${BASE}/v1/capabilities`);
  return res.json();
}

export async function probeMedia(path: string): Promise<string> {
  const res = await fetch(`${BASE}/v1/media/probe`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path }),
  });
  return res.text();
}

export async function orchestratorCreateTrack(
  sequenceId: string,
  trackType: string,
  laneIndex: number,
  name: string,
): Promise<Track> {
  const res = await fetch(`${BASE}/v1/sequences/${sequenceId}/tracks`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ track_type: trackType, lane_index: laneIndex, name }),
  });
  return res.json();
}

export async function orchestratorListTracks(sequenceId: string): Promise<Track[]> {
  const res = await fetch(`${BASE}/v1/sequences/${sequenceId}/tracks`);
  return res.json();
}

export async function orchestratorDeleteTrack(sequenceId: string, trackId: string): Promise<{ status: string }> {
  const res = await fetch(`${BASE}/v1/sequences/${sequenceId}/tracks/${trackId}`, { method: "DELETE" });
  if (!res.ok && res.status !== 404) throw new Error(await res.text());
  return { status: res.status === 404 ? "already_deleted" : "deleted" };
}

export async function orchestratorCreateClip(
  sequenceId: string,
  trackId: string,
  assetId: string,
  inTick: number,
  outTick: number,
): Promise<Clip> {
  const res = await fetch(`${BASE}/v1/sequences/${sequenceId}/clips`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ track_id: trackId, asset_id: assetId, in_tick: inTick, out_tick: outTick, src_in_tick: 0, speed_ratio: 1.0 }),
  });
  return res.json();
}

export async function orchestratorListClips(sequenceId: string): Promise<Clip[]> {
  const res = await fetch(`${BASE}/v1/sequences/${sequenceId}/clips`);
  return res.json();
}

export async function importMedia(projectId: string, filePath: string): Promise<Asset> {
  const res = await fetch(`${BASE}/v1/projects/${projectId}/assets/import`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path: filePath }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function listProjectAssets(projectId: string): Promise<Asset[]> {
  const res = await fetch(`${BASE}/v1/projects/${projectId}/assets`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getAsset(assetId: string): Promise<Asset> {
  const res = await fetch(`${BASE}/v1/assets/${assetId}`);
  return res.json();
}

export async function fetchFrame(path: string, timeSeconds: number): Promise<string> {
  const res = await fetch(`${BASE}/v1/media/frame`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path, time_seconds: timeSeconds }),
  });
  if (!res.ok) {
    const text = await res.text();
    try {
      const err = JSON.parse(text) as { detail?: string };
      throw new Error(err.detail ?? text);
    } catch {
      throw new Error(text || `frame fetch failed: ${res.status}`);
    }
  }
  const data = (await res.json()) as MediaFrameResponse;
  if (!data.base64) {
    throw new Error(data.error ?? "Missing frame payload");
  }
  return data.base64;
}

export function getStreamUrl(path: string): string {
  return `${BASE}/v1/media/stream?path=${encodeURIComponent(path)}`;
}
