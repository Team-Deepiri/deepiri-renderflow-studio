import { describe, it, expect, beforeEach } from "vitest";
import { createInitialState, createHistoryStack } from "../state";
import type { StudioState, HistoryStack } from "../state";
import { addMarker, jumpToNextMarker, removeMarker } from "./markers";

let state: StudioState;
let history: HistoryStack;

beforeEach(() => {
  state = createInitialState();
  history = createHistoryStack();
  // playheadTick = 288, markers = []
});

describe("addMarker", () => {
  it("adds a marker at the current playhead", () => {
    const result = addMarker(state, history);
    expect(result.ui.markers).toContain(288);
  });

  it("deduplicates markers at the same tick", () => {
    addMarker(state, history);
    addMarker(state, history);
    const count = state.ui.markers.filter((m) => m === 288).length;
    expect(count).toBe(1);
  });

  it("keeps markers sorted ascending", () => {
    state.timeline.playheadTick = 500;
    addMarker(state, history);
    state.timeline.playheadTick = 100;
    addMarker(state, history);
    state.timeline.playheadTick = 300;
    addMarker(state, history);
    expect(state.ui.markers).toEqual([100, 300, 500]);
  });

  it("commits to history", () => {
    addMarker(state, history);
    expect(history.past.length).toBeGreaterThan(0);
  });
});

describe("jumpToNextMarker", () => {
  it("no-op when no markers exist", () => {
    const before = state.timeline.playheadTick;
    jumpToNextMarker(state);
    expect(state.timeline.playheadTick).toBe(before);
  });

  it("jumps to the next marker after the playhead", () => {
    state.ui.markers = [100, 300, 600];
    state.timeline.playheadTick = 200;
    jumpToNextMarker(state);
    expect(state.timeline.playheadTick).toBe(300);
  });

  it("wraps around to 0 when past the last marker", () => {
    state.ui.markers = [100, 300];
    state.timeline.playheadTick = 400;
    jumpToNextMarker(state);
    expect(state.timeline.playheadTick).toBe(0);
  });

  it("jumps past a marker at the same tick (strictly greater)", () => {
    state.ui.markers = [100, 300, 600];
    state.timeline.playheadTick = 100;
    jumpToNextMarker(state);
    expect(state.timeline.playheadTick).toBe(300);
  });
});

describe("removeMarker", () => {
  it("removes a marker at the given tick", () => {
    state.ui.markers = [100, 300, 600];
    removeMarker(state, 300);
    expect(state.ui.markers).toEqual([100, 600]);
  });

  it("no-op when marker does not exist", () => {
    state.ui.markers = [100, 300];
    removeMarker(state, 999);
    expect(state.ui.markers).toEqual([100, 300]);
  });
});
