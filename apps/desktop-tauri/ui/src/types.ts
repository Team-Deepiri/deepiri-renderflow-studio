/**
 * Shared TypeScript types for the Studio UI layer.
 *
 * NOTE: backendApi.ts already exports server-side Track/Clip/Asset types
 * (string UUIDs, snake_case). Local UI types use the Ui* prefix to avoid
 * collision and use numeric IDs for DOM key stability.
 */

export type { Asset } from "./backendApi";

/** A clip as rendered in the timeline UI. */
export type UiClip = {
  id: number;
  serverId?: string;
  label: string;
  inTick: number;
  outTick: number;
  color: string;
};

/** A track as rendered in the timeline UI. */
export type UiTrack = {
  id: number;
  serverId?: string;
  name: string;
  kind: "Video" | "Audio";
  lane_index: number;
  clips: UiClip[];
};

/** The playback/edit state of the timeline. */
export type TimelineState = {
  fps: number;
  durationTicks: number;
  playheadTick: number;
  tracks: UiTrack[];
};

/** UI-only state: zoom, selection, markers. */
export type TimelineUiState = {
  zoom: number;
  selectedClipId: number | null;
  activeTrackId: number | null;
  markers: number[];
};

/** A point-in-time snapshot used for undo/redo. */
export type TimelineSnapshot = {
  timelineState: TimelineState;
  timelineUiState: TimelineUiState;
};
