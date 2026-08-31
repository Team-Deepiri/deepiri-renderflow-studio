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
  /** DOM/selection key. Local to this session, not persisted. */
  id: number;
  /** Server clip id. Minted client-side at creation and stable across saves,
   *  so persisting a timeline updates clip rows instead of replacing them
  */
  clipId: string;
  /** Linked asset id. Undefined for clips with no media behind them. */
  assetId?: string;
  label: string;
  inTick: number;
  outTick: number;
  color: string;
};

/** Mints a stable server clip id. Client-side so a clip keeps one identity
 *  from creation through every save. */
export function newClipId(): string {
  return crypto.randomUUID();
}

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

/** A project template definition. */
export type ProjectTemplate = {
  id: string;
  name: string;
  description: string;
  tracks: { name: string; kind: "Video" | "Audio"; lane_index: number }[];
};

export const PROJECT_TEMPLATES: ProjectTemplate[] = [
  {
    id: "blank",
    name: "Blank",
    description:
      "Clean slate. One video track and one audio track — add what you need.",
    tracks: [
      { name: "V1", kind: "Video", lane_index: 0 },
      { name: "A1", kind: "Audio", lane_index: 0 },
    ],
  },
  {
    id: "social-clip",
    name: "Social Clip",
    description:
      "Lean setup for short-form content (TikTok, Reels, Shorts). One video with music and SFX tracks.",
    tracks: [
      { name: "V1 Main", kind: "Video", lane_index: 0 },
      { name: "A1 Music", kind: "Audio", lane_index: 0 },
      { name: "A2 SFX", kind: "Audio", lane_index: 1 },
    ],
  },
  {
    id: "documentary",
    name: "Documentary",
    description:
      "Full long-form setup: A-roll, B-roll, titles, dialog, narration, music, and ambience.",
    tracks: [
      { name: "V1 A-Roll", kind: "Video", lane_index: 2 },
      { name: "V2 B-Roll", kind: "Video", lane_index: 1 },
      { name: "V3 Titles", kind: "Video", lane_index: 0 },
      { name: "A1 Dialog", kind: "Audio", lane_index: 0 },
      { name: "A2 Narration", kind: "Audio", lane_index: 1 },
      { name: "A3 Music", kind: "Audio", lane_index: 2 },
      { name: "A4 Ambience", kind: "Audio", lane_index: 3 },
    ],
  },
  {
    id: "multi-cam",
    name: "Multi-Cam",
    description:
      "Three camera angles (main, wide, close-up) with live audio and music. Great for events and concerts.",
    tracks: [
      { name: "V1 Cam 1 Main", kind: "Video", lane_index: 2 },
      { name: "V2 Cam 2 Wide", kind: "Video", lane_index: 1 },
      { name: "V3 Cam 3 Close", kind: "Video", lane_index: 0 },
      { name: "A1 Live Audio", kind: "Audio", lane_index: 0 },
      { name: "A2 Music", kind: "Audio", lane_index: 1 },
    ],
  },
  {
    id: "tutorial",
    name: "Tutorial / Screencast",
    description:
      "For software demos, courses, and YouTube tutorials. Screen recording as main with a webcam picture-in-picture overlay.",
    tracks: [
      { name: "V1 Screen Recording", kind: "Video", lane_index: 1 },
      { name: "V2 Webcam (PiP)", kind: "Video", lane_index: 0 },
      { name: "A1 Voiceover", kind: "Audio", lane_index: 0 },
      { name: "A2 Notification SFX", kind: "Audio", lane_index: 1 },
    ],
  },
  {
    id: "music-video",
    name: "Music Video",
    description:
      "Performance editing with a dedicated VFX layer. Includes a song master track and stems for fine mixing.",
    tracks: [
      { name: "V1 Performance", kind: "Video", lane_index: 2 },
      { name: "V2 B-Roll / Cutaways", kind: "Video", lane_index: 1 },
      { name: "V3 VFX / Effects", kind: "Video", lane_index: 0 },
      { name: "A1 Song Master", kind: "Audio", lane_index: 0 },
      { name: "A2 Stems", kind: "Audio", lane_index: 1 },
    ],
  },
];
