import { invoke } from "@tauri-apps/api/core";

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
  status: "queued" | "processing" | "completed" | "failed";
  result_asset_id?: string;
  error_message?: string;
  created_at: string;
  completed_at?: string;
}

export interface RenderJob {
  id: string;
  project_id: string;
  sequence_id?: string;
  preset: string;
  status: "pending" | "rendering" | "completed" | "failed";
  progress: number;
  output_uri?: string;
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

export function orchestratorHealth(): Promise<{ status: string }> {
  return invoke("orchestrator_health", { baseUrl: null });
}

export function vulkanDiscover(): Promise<unknown> {
  return invoke("vulkan_discover", {});
}

export function timelineResolveActive(payload: unknown): Promise<unknown> {
  return invoke("timeline_resolve_active", { payload });
}

export function submitAiJob(prompt: string, mode = "scene-generation"): Promise<{ job_id: string; status: string }> {
  return invoke("submit_ai_job", {
    projectId: "renderflow-local-project",
    mode,
    prompt,
    baseUrl: null,
  });
}

export function getAiJob(jobId: string): Promise<AIJob> {
  return invoke("get_ai_job", { jobId, baseUrl: null });
}

export function orchestratorListProjects(): Promise<PaginatedResponse<Project>> {
  return invoke("orchestrator_list_projects_paginated", {
    page: 1,
    pageSize: 20,
    baseUrl: null,
  });
}

export function orchestratorCreateProject(
  name: string,
  fpsNum = 24,
  fpsDen = 1,
): Promise<Project> {
  return invoke("orchestrator_create_project", {
    name,
    fpsNum,
    fpsDen,
    baseUrl: null,
  });
}

export function orchestratorGetProject(projectId: string): Promise<Project> {
  return invoke("orchestrator_get_project", { projectId, baseUrl: null });
}

export function orchestratorDeleteProject(projectId: string): Promise<{ status: string }> {
  return invoke("orchestrator_delete_project", { projectId, baseUrl: null });
}

export function orchestratorListSequences(projectId: string): Promise<Sequence[]> {
  return invoke("orchestrator_list_sequences", { projectId, baseUrl: null });
}

export function orchestratorCreateSequence(
  projectId: string,
  name: string,
  resolutionW = 1920,
  resolutionH = 1080,
): Promise<Sequence> {
  return invoke("orchestrator_create_sequence", {
    projectId,
    name,
    resolutionW,
    resolutionH,
    baseUrl: null,
  });
}

export function orchestratorGetCapabilities(): Promise<Capabilities> {
  return invoke("orchestrator_get_capabilities", { baseUrl: null });
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

const BASE = "http://127.0.0.1:8080";

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
