import type { StudioState, HistoryStack } from "../state";
import type { TimelineSnapshot } from "../types";

const HISTORY_CAP = 80;

/** Creates a deep-copy snapshot of the timeline + ui portions of state. */
export function snapshotState(state: StudioState): TimelineSnapshot {
  return JSON.parse(
    JSON.stringify({
      timelineState: state.timeline,
      timelineUiState: state.ui,
    })
  ) as TimelineSnapshot;
}

/** Applies a snapshot onto state, replacing timeline and ui in-place. */
export function applySnapshot(
  state: StudioState,
  snapshot: TimelineSnapshot
): StudioState {
  state.timeline = JSON.parse(JSON.stringify(snapshot.timelineState));
  state.ui = JSON.parse(JSON.stringify(snapshot.timelineUiState));
  return state;
}

/**
 * Saves the current state to the undo stack.
 * No-op when history.suppressHistory is true.
 * Caps the past stack at HISTORY_CAP entries (oldest dropped).
 */
export function commitHistory(
  state: StudioState,
  history: HistoryStack,
  _label: string
): void {
  if (history.suppressHistory) return;
  history.past.push(snapshotState(state));
  if (history.past.length > HISTORY_CAP) {
    history.past.shift();
  }
  history.future = [];
}

/**
 * Undoes the last committed operation.
 * No-op when the past stack is empty.
 */
export function undoHistory(
  state: StudioState,
  history: HistoryStack
): StudioState {
  if (history.past.length === 0) return state;
  history.future.push(snapshotState(state));
  const snap = history.past.pop()!;
  return applySnapshot(state, snap);
}

/**
 * Redoes the last undone operation.
 * No-op when the future stack is empty.
 */
export function redoHistory(
  state: StudioState,
  history: HistoryStack
): StudioState {
  if (history.future.length === 0) return state;
  history.past.push(snapshotState(state));
  const snap = history.future.pop()!;
  return applySnapshot(state, snap);
}
