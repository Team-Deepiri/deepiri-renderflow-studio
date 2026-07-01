import type { StudioState, HistoryStack } from "../state";
import { commitHistory } from "./history";

/** Adds a marker at the current playhead position. Deduplicates and sorts. */
export function addMarker(
  state: StudioState,
  history: HistoryStack
): StudioState {
  const tick = state.timeline.playheadTick;
  if (!state.ui.markers.includes(tick)) {
    commitHistory(state, history, "add marker");
    state.ui.markers = [...state.ui.markers, tick].sort((a, b) => a - b);
  }
  return state;
}

/**
 * Moves the playhead to the next marker after the current playhead.
 * Wraps around to 0 when past the last marker.
 * No-op when there are no markers.
 */
export function jumpToNextMarker(state: StudioState): StudioState {
  if (state.ui.markers.length === 0) return state;
  const ph = state.timeline.playheadTick;
  const next = state.ui.markers.find((m) => m > ph);
  state.timeline.playheadTick = next !== undefined ? next : 0;
  return state;
}

/** Removes a marker at the given tick. No-op if not found. */
export function removeMarker(state: StudioState, tick: number): StudioState {
  state.ui.markers = state.ui.markers.filter((m) => m !== tick);
  return state;
}
