import { describe, it, expect, beforeEach } from "vitest";
import { createInitialState, createHistoryStack } from "../state";
import type { StudioState, HistoryStack } from "../state";
import {
  snapshotState,
  applySnapshot,
  commitHistory,
  undoHistory,
  redoHistory,
} from "./history";

let state: StudioState;
let history: HistoryStack;

beforeEach(() => {
  state = createInitialState();
  history = createHistoryStack();
});

describe("snapshotState", () => {
  it("captures current timeline and ui", () => {
    const snap = snapshotState(state);
    expect(snap.timelineState.fps).toBe(24);
    expect(snap.timelineUiState.zoom).toBe(1);
  });

  it("returns a deep copy — mutations do not affect snapshot", () => {
    const snap = snapshotState(state);
    state.timeline.playheadTick = 9999;
    expect(snap.timelineState.playheadTick).toBe(288);
  });

  it("deep copies nested clips array", () => {
    const snap = snapshotState(state);
    state.timeline.tracks[0].clips[0].label = "MUTATED";
    expect(snap.timelineState.tracks[0].clips[0].label).toBe("Clip A");
  });
});

describe("applySnapshot", () => {
  it("restores timeline state from snapshot", () => {
    const snap = snapshotState(state);
    state.timeline.playheadTick = 9999;
    const result = applySnapshot(state, snap);
    expect(result.timeline.playheadTick).toBe(288);
  });

  it("restores ui state from snapshot", () => {
    const snap = snapshotState(state);
    state.ui.zoom = 5;
    const result = applySnapshot(state, snap);
    expect(result.ui.zoom).toBe(1);
  });
});

describe("commitHistory", () => {
  it("pushes a snapshot onto past", () => {
    commitHistory(state, history, "test");
    expect(history.past).toHaveLength(1);
  });

  it("clears the future on commit", () => {
    commitHistory(state, history, "first");
    history.future.push(snapshotState(state));
    commitHistory(state, history, "second");
    expect(history.future).toHaveLength(0);
  });

  it("does nothing when suppressHistory is true", () => {
    history.suppressHistory = true;
    commitHistory(state, history, "suppressed");
    expect(history.past).toHaveLength(0);
  });

  it("caps the stack at 80 entries", () => {
    for (let i = 0; i < 85; i++) {
      commitHistory(state, history, `op-${i}`);
    }
    expect(history.past.length).toBeLessThanOrEqual(80);
  });
});

describe("undoHistory", () => {
  it("no-op when past is empty", () => {
    const original = state.timeline.playheadTick;
    const result = undoHistory(state, history);
    expect(result.timeline.playheadTick).toBe(original);
  });

  it("restores previous state", () => {
    commitHistory(state, history, "before change");
    state.timeline.playheadTick = 1200;
    const result = undoHistory(state, history);
    expect(result.timeline.playheadTick).toBe(288);
  });

  it("pushes current state onto future", () => {
    commitHistory(state, history, "step");
    state.timeline.playheadTick = 1200;
    undoHistory(state, history);
    expect(history.future).toHaveLength(1);
  });

  it("pops from past", () => {
    commitHistory(state, history, "step");
    undoHistory(state, history);
    expect(history.past).toHaveLength(0);
  });
});

describe("redoHistory", () => {
  it("no-op when future is empty", () => {
    const original = state.timeline.playheadTick;
    const result = redoHistory(state, history);
    expect(result.timeline.playheadTick).toBe(original);
  });

  it("restores next state", () => {
    commitHistory(state, history, "before");
    state.timeline.playheadTick = 1200;
    undoHistory(state, history);
    // Now redo should restore playheadTick=1200
    // But we need the current state to be 288 (restored by undo)
    // future has snapshot of playheadTick=1200
    const result = redoHistory(state, history);
    expect(result.timeline.playheadTick).toBe(1200);
  });

  it("pushes current state onto past", () => {
    commitHistory(state, history, "before");
    state.timeline.playheadTick = 1200;
    undoHistory(state, history);
    redoHistory(state, history);
    expect(history.past).toHaveLength(1);
  });
});
