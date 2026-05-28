import type { StudioState, HistoryStack } from "../state";
import type { UiClip, UiTrack, Asset } from "../types";
import { commitHistory } from "./history";

const CLIP_COLORS = [
  "#4d7dff", "#18b487", "#ff8c42", "#a855f7",
  "#ec4899", "#f59e0b", "#14b8a6", "#ef4444",
];

/** Finds a clip by numeric ID across all tracks. Returns null if not found. */
export function getClipById(
  state: StudioState,
  clipId: number
): { track: UiTrack; clip: UiClip } | null {
  for (const track of state.timeline.tracks) {
    const clip = track.clips.find((c) => c.id === clipId);
    if (clip) return { track, clip };
  }
  return null;
}

/**
 * Splits the currently selected clip at the playhead.
 * No-op if:
 *   - no clip is selected
 *   - playhead is at or within 1 tick of the clip's start (≤ inTick+1)
 *   - playhead is at or within 1 tick of the clip's end (≥ outTick-1)
 */
export function splitClip(
  state: StudioState,
  history: HistoryStack
): StudioState {
  if (state.ui.selectedClipId === null) return state;
  const found = getClipById(state, state.ui.selectedClipId);
  if (!found) return state;
  const { track, clip } = found;
  const ph = state.timeline.playheadTick;

  if (ph <= clip.inTick + 1 || ph >= clip.outTick - 1) return state;

  commitHistory(state, history, "split clip");

  const newClip: UiClip = {
    id: state.nextClipId++,
    serverId: undefined,
    label: clip.label,
    inTick: ph,
    outTick: clip.outTick,
    color: clip.color,
  };
  clip.outTick = ph;
  const idx = track.clips.indexOf(clip);
  track.clips.splice(idx + 1, 0, newClip);
  return state;
}

/**
 * Deletes the currently selected clip.
 * No-op if no clip is selected or clip is not found.
 */
export function deleteClip(
  state: StudioState,
  history: HistoryStack
): StudioState {
  if (state.ui.selectedClipId === null) return state;
  const found = getClipById(state, state.ui.selectedClipId);
  if (!found) return state;

  commitHistory(state, history, "delete clip");

  const { track, clip } = found;
  track.clips = track.clips.filter((c) => c !== clip);
  state.ui.selectedClipId = null;
  return state;
}

/**
 * Moves a clip by `deltaInTick` ticks.
 * Clamps so: inTick >= 0 and outTick <= durationTicks.
 */
export function moveClip(
  state: StudioState,
  clipId: number,
  deltaInTick: number,
  history: HistoryStack
): StudioState {
  const found = getClipById(state, clipId);
  if (!found) return state;
  const { clip } = found;
  const len = clip.outTick - clip.inTick;
  const maxDelta = state.timeline.durationTicks - len;

  let newIn = clip.inTick + deltaInTick;
  newIn = Math.max(0, Math.min(newIn, maxDelta));

  clip.inTick = newIn;
  clip.outTick = newIn + len;
  return state;
}

/**
 * Trims the in or out point of a clip by `deltaInTick` ticks.
 * Enforces a minimum clip length of 2 ticks.
 */
export function trimClip(
  state: StudioState,
  clipId: number,
  side: "in" | "out",
  deltaInTick: number
): StudioState {
  const found = getClipById(state, clipId);
  if (!found) return state;
  const { clip } = found;

  if (side === "in") {
    const newIn = Math.min(clip.inTick + deltaInTick, clip.outTick - 2);
    clip.inTick = Math.max(0, newIn);
  } else {
    const newOut = Math.max(clip.outTick + deltaInTick, clip.inTick + 2);
    clip.outTick = Math.min(state.timeline.durationTicks, newOut);
  }
  return state;
}

/**
 * Inserts a new clip at the end of the active track.
 * Duration = round(asset.duration_ms / 1000 * fps), fallback 160 ticks.
 * No-op if no active track is set.
 */
export function insertClipFromAsset(
  state: StudioState,
  asset: Asset,
  history: HistoryStack
): StudioState {
  if (state.ui.activeTrackId === null) return state;
  const track = state.timeline.tracks.find(
    (t) => t.id === state.ui.activeTrackId
  );
  if (!track) return state;

  commitHistory(state, history, "insert clip");

  const durationTicks =
    asset.duration_ms && asset.duration_ms > 0
      ? Math.round((asset.duration_ms / 1000) * state.timeline.fps)
      : 160;

  const lastClip = track.clips[track.clips.length - 1];
  const inTick = lastClip ? lastClip.outTick : 0;

  const newClip: UiClip = {
    id: state.nextClipId++,
    serverId: asset.id,
    label: asset.uri.split("/").pop() ?? asset.id,
    inTick,
    outTick: inTick + durationTicks,
    color: CLIP_COLORS[state.nextClipId % CLIP_COLORS.length],
  };
  track.clips.push(newClip);
  return state;
}
