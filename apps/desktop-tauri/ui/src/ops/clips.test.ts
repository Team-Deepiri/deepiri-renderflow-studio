import { describe, it, expect, beforeEach } from "vitest";
import { createInitialState, createHistoryStack } from "../state";
import type { StudioState, HistoryStack } from "../state";
import type { Asset } from "../backendApi";
import {
  getClipById,
  splitClip,
  deleteClip,
  moveClip,
  trimClip,
  insertClipFromAsset,
} from "./clips";

let state: StudioState;
let history: HistoryStack;

beforeEach(() => {
  state = createInitialState();
  history = createHistoryStack();
  // V1 Main: clip 101 [0..480], clip 102 [480..960]
  // V2 Overlay: clip 201 [240..720]
  // A1 Dialog: clip 301 [0..960]
  // playheadTick = 288, fps = 24, durationTicks = 2400
});

// ── getClipById ──────────────────────────────────────────────────────────────

describe("getClipById", () => {
  it("returns the track and clip when found", () => {
    const found = getClipById(state, 101);
    expect(found).not.toBeNull();
    expect(found!.clip.id).toBe(101);
    expect(found!.track.id).toBe(1);
  });

  it("returns null for an unknown clip id", () => {
    expect(getClipById(state, 999)).toBeNull();
  });
});

// ── splitClip ────────────────────────────────────────────────────────────────

describe("splitClip", () => {
  it("splits the selected clip at the playhead", () => {
    // playhead=288, clip 101: inTick=0, outTick=480
    state.ui.selectedClipId = 101;
    const result = splitClip(state, history);
    const track = result.timeline.tracks[0];
    // Original clip truncated at 288; new clip from 288..480
    const orig = track.clips.find((c) => c.id === 101)!;
    expect(orig.outTick).toBe(288);
    const newClip = track.clips.find((c) => c.id !== 101 && c.id !== 102)!;
    expect(newClip.inTick).toBe(288);
    expect(newClip.outTick).toBe(480);
  });

  it("no-op when no clip is selected", () => {
    state.ui.selectedClipId = null;
    const before = state.timeline.tracks[0].clips.length;
    splitClip(state, history);
    expect(state.timeline.tracks[0].clips.length).toBe(before);
  });

  it("no-op when playhead is at clip start boundary (≤ inTick+1)", () => {
    state.ui.selectedClipId = 101;
    state.timeline.playheadTick = 0; // at inTick
    const before = state.timeline.tracks[0].clips.length;
    splitClip(state, history);
    expect(state.timeline.tracks[0].clips.length).toBe(before);
  });

  it("no-op when playhead is at clip end boundary (≥ outTick-1)", () => {
    state.ui.selectedClipId = 101;
    state.timeline.playheadTick = 479; // outTick-1
    const before = state.timeline.tracks[0].clips.length;
    splitClip(state, history);
    expect(state.timeline.tracks[0].clips.length).toBe(before);
  });

  it("commits to history when split occurs", () => {
    state.ui.selectedClipId = 101;
    splitClip(state, history);
    expect(history.past.length).toBeGreaterThan(0);
  });

  it("increments nextClipId", () => {
    state.ui.selectedClipId = 101;
    const before = state.nextClipId;
    splitClip(state, history);
    expect(state.nextClipId).toBe(before + 1);
  });
});

// ── deleteClip ───────────────────────────────────────────────────────────────

describe("deleteClip", () => {
  it("removes the selected clip from its track", () => {
    state.ui.selectedClipId = 101;
    const result = deleteClip(state, history);
    const ids = result.timeline.tracks[0].clips.map((c) => c.id);
    expect(ids).not.toContain(101);
  });

  it("clears selectedClipId after deletion", () => {
    state.ui.selectedClipId = 101;
    const result = deleteClip(state, history);
    expect(result.ui.selectedClipId).toBeNull();
  });

  it("no-op when no clip is selected", () => {
    state.ui.selectedClipId = null;
    const before = state.timeline.tracks[0].clips.length;
    deleteClip(state, history);
    expect(state.timeline.tracks[0].clips.length).toBe(before);
  });

  it("commits to history when deleted", () => {
    state.ui.selectedClipId = 101;
    deleteClip(state, history);
    expect(history.past.length).toBeGreaterThan(0);
  });
});

// ── moveClip ─────────────────────────────────────────────────────────────────

describe("moveClip", () => {
  it("shifts clip by deltaInTick", () => {
    const result = moveClip(state, 101, 50, history);
    const clip = result.timeline.tracks[0].clips.find((c) => c.id === 101)!;
    expect(clip.inTick).toBe(50);
    expect(clip.outTick).toBe(530);
  });

  it("clamps clip to timeline start (inTick >= 0)", () => {
    const result = moveClip(state, 101, -9999, history);
    const clip = result.timeline.tracks[0].clips.find((c) => c.id === 101)!;
    expect(clip.inTick).toBe(0);
  });

  it("clamps clip so outTick <= durationTicks", () => {
    const result = moveClip(state, 101, 9999, history);
    const clip = result.timeline.tracks[0].clips.find((c) => c.id === 101)!;
    expect(clip.outTick).toBeLessThanOrEqual(state.timeline.durationTicks);
  });

  it("no-op for unknown clip id", () => {
    const before = state.timeline.tracks[0].clips[0].inTick;
    moveClip(state, 999, 50, history);
    expect(state.timeline.tracks[0].clips[0].inTick).toBe(before);
  });
});

// ── trimClip ─────────────────────────────────────────────────────────────────

describe("trimClip", () => {
  it("trims the in point of a clip", () => {
    const result = trimClip(state, 101, "in", 50);
    const clip = result.timeline.tracks[0].clips.find((c) => c.id === 101)!;
    expect(clip.inTick).toBe(50);
    expect(clip.outTick).toBe(480); // unchanged
  });

  it("trims the out point of a clip", () => {
    const result = trimClip(state, 101, "out", -50);
    const clip = result.timeline.tracks[0].clips.find((c) => c.id === 101)!;
    expect(clip.outTick).toBe(430);
    expect(clip.inTick).toBe(0); // unchanged
  });

  it("enforces minimum 2-tick clip length on in-trim", () => {
    // clip 101: inTick=0, outTick=480, length=480
    // trying to trim in past outTick-2=478 should clamp to 478
    const result = trimClip(state, 101, "in", 9999);
    const clip = result.timeline.tracks[0].clips.find((c) => c.id === 101)!;
    expect(clip.outTick - clip.inTick).toBeGreaterThanOrEqual(2);
  });

  it("enforces minimum 2-tick clip length on out-trim", () => {
    const result = trimClip(state, 101, "out", -9999);
    const clip = result.timeline.tracks[0].clips.find((c) => c.id === 101)!;
    expect(clip.outTick - clip.inTick).toBeGreaterThanOrEqual(2);
  });

  it("no-op for unknown clip id", () => {
    const before = state.timeline.tracks[0].clips[0].inTick;
    trimClip(state, 999, "in", 10);
    expect(state.timeline.tracks[0].clips[0].inTick).toBe(before);
  });
});

// ── insertClipFromAsset ──────────────────────────────────────────────────────

describe("insertClipFromAsset", () => {
  const makeAsset = (overrides: Partial<Asset> = {}): Asset => ({
    id: "asset-1",
    project_id: "proj-1",
    kind: "video",
    uri: "file:///test.mp4",
    sha256: "abc",
    duration_ms: 2000, // 2 seconds → 48 ticks at 24fps
    meta_jsonb: { proxy_status: "ready" },
    ...overrides,
  });

  it("inserts a clip on the active track", () => {
    state.ui.activeTrackId = 1;
    const before = state.timeline.tracks[0].clips.length;
    insertClipFromAsset(state, makeAsset(), history);
    expect(state.timeline.tracks[0].clips.length).toBe(before + 1);
  });

  it("uses duration_ms to set clip length: round(ms/1000 * fps) ticks", () => {
    state.ui.activeTrackId = 1;
    // 2000ms at 24fps = 48 ticks
    insertClipFromAsset(state, makeAsset({ duration_ms: 2000 }), history);
    const clips = state.timeline.tracks[0].clips;
    const newClip = clips[clips.length - 1];
    expect(newClip.outTick - newClip.inTick).toBe(48);
  });

  it("falls back to 160 ticks when duration_ms is 0", () => {
    state.ui.activeTrackId = 1;
    insertClipFromAsset(state, makeAsset({ duration_ms: 0 }), history);
    const clips = state.timeline.tracks[0].clips;
    const newClip = clips[clips.length - 1];
    expect(newClip.outTick - newClip.inTick).toBe(160);
  });

  it("no-op when no active track is set", () => {
    state.ui.activeTrackId = null;
    const before = state.timeline.tracks[0].clips.length;
    insertClipFromAsset(state, makeAsset(), history);
    expect(state.timeline.tracks[0].clips.length).toBe(before);
  });

  it("commits to history on insert", () => {
    state.ui.activeTrackId = 1;
    insertClipFromAsset(state, makeAsset(), history);
    expect(history.past.length).toBeGreaterThan(0);
  });

  it("increments nextClipId", () => {
    state.ui.activeTrackId = 1;
    const before = state.nextClipId;
    insertClipFromAsset(state, makeAsset(), history);
    expect(state.nextClipId).toBe(before + 1);
  });
});
