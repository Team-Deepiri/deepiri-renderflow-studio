import type { StudioState, HistoryStack } from "../state";
import type { UiClip, UiTrack, Asset } from "../types";
import { newClipId } from "../types";
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
    clipId: newClipId(),
    // Inherit the source's asset: the fragment is the same media, so it stays
    // previewable and persists like any other clip.
    assetId: clip.assetId,
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
 * Deletes the selected clip and pulls everything after it on the same track
 * back by its length, so no gap is left behind.
 *
 * The plain delete leaves the hole in place — that stays the default, because
 * closing gaps is not always what you want.
 */
export function rippleDeleteClip(
  state: StudioState,
  history: HistoryStack
): StudioState {
  if (state.ui.selectedClipId === null) return state;
  const found = getClipById(state, state.ui.selectedClipId);
  if (!found) return state;

  commitHistory(state, history, "ripple delete clip");

  const { track, clip } = found;
  const gap = clip.outTick - clip.inTick;
  const removedAt = clip.inTick;

  track.clips = track.clips.filter((c) => c !== clip);
  for (const c of track.clips) {
    if (c.inTick >= removedAt) {
      c.inTick -= gap;
      c.outTick -= gap;
    }
  }
  state.ui.selectedClipId = null;
  return state;
}

/**
 * Copies the selected clip in directly after itself and selects the copy.
 * Returns the new clip, or null when nothing is selected.
 */
export function duplicateClip(
  state: StudioState,
  history: HistoryStack
): UiClip | null {
  if (state.ui.selectedClipId === null) return null;
  const found = getClipById(state, state.ui.selectedClipId);
  if (!found) return null;

  commitHistory(state, history, "duplicate clip");

  const { track, clip } = found;
  const len = clip.outTick - clip.inTick;
  const copy: UiClip = {
    id: state.nextClipId++,
    // Its own clip row, so a fresh clipId — but the same media underneath, so
    // the asset carries over and the copy stays previewable and persistable.
    clipId: newClipId(),
    assetId: clip.assetId,
    label: clip.label,
    inTick: clip.outTick,
    outTick: clip.outTick + len,
    color: clip.color,
  };

  track.clips.splice(track.clips.indexOf(clip) + 1, 0, copy);
  state.ui.selectedClipId = copy.id;

  const tail = copy.outTick + state.timeline.fps * 2;
  if (tail > state.timeline.durationTicks) state.timeline.durationTicks = tail;

  return copy;
}

/**
 * Snaps a dragged tick to the nearest clip edge, the playhead, or zero when
 * one is within `threshold` ticks. Edges of `movingClipId` are skipped so a
 * clip never snaps to itself.
 *
 * Returns `tick` unchanged when nothing is close enough, which is what keeps
 * single-frame nudges possible.
 */
export function snapTick(
  state: StudioState,
  tick: number,
  movingClipId: number | null,
  threshold: number
): number {
  const targets: number[] = [0, state.timeline.playheadTick];
  for (const track of state.timeline.tracks) {
    for (const clip of track.clips) {
      if (clip.id === movingClipId) continue;
      targets.push(clip.inTick, clip.outTick);
    }
  }

  let best = tick;
  let bestDist = threshold;
  for (const target of targets) {
    const dist = Math.abs(target - tick);
    if (dist <= bestDist) {
      bestDist = dist;
      best = target;
    }
  }
  return best;
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
 * What the clip reads as on the timeline: the asset's display name (AI
 * clips carry their prompt there), else the file name. Splits on both
 * separators — asset URIs are absolute paths, backslashed on Windows.
 */
function clipLabel(asset: Asset): string {
  const name = asset.meta_jsonb?.name;
  if (name) return name;
  return asset.uri.split(/[\\/]/).pop() || asset.id;
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
    clipId: newClipId(),
    assetId: asset.id,
    label: clipLabel(asset),
    inTick,
    outTick: inTick + durationTicks,
    color: CLIP_COLORS[state.nextClipId % CLIP_COLORS.length],
  };
  track.clips.push(newClip);
  return state;
}

/**
 * Drops an asset onto the first video track — the shared path for imports,
 * drag-and-drop, and accepted AI clips.
 *
 * Clears the starter placeholder clips (the ones with no linked asset) the
 * first time real media arrives, appends the asset, and grows the timeline
 * so the new clip is reachable. Returns the inserted clip, or null when
 * there is no video track to insert into.
 */
export function insertAssetIntoVideoTrack(
  state: StudioState,
  asset: Asset,
  history: HistoryStack
): UiClip | null {
  const track = state.timeline.tracks.find((t) => t.kind === "Video");
  if (!track) return null;

  // Keyed on assetId, not serverId: a clip inserted since the last save has no
  // serverId yet, and dropping those here would discard the user's unsaved work.
  track.clips = track.clips.filter((c) => c.assetId);
  state.ui.activeTrackId = track.id;
  insertClipFromAsset(state, asset, history);

  const inserted = track.clips[track.clips.length - 1] ?? null;

  const maxOut = track.clips.reduce((m, c) => Math.max(m, c.outTick), 0);
  const tail = maxOut + state.timeline.fps * 2;
  if (tail > state.timeline.durationTicks) state.timeline.durationTicks = tail;

  return inserted;
}
