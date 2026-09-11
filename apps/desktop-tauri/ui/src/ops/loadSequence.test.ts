import { describe, it, expect } from "vitest";
import { createInitialState } from "../state";
import type { Clip, Track } from "../backendApi";
import { loadSequenceTracks, type SequenceApi } from "./loadSequence";

function track(over: Partial<Track> & { id: string }): Track {
  return {
    sequence_id: "seq-1",
    track_type: "video",
    lane_index: 0,
    name: "V1",
    muted: false,
    locked: false,
    solo: false,
    ...over,
  };
}

function clip(over: Partial<Clip> & { id: string; track_id: string }): Clip {
  return {
    asset_id: "asset-1",
    name: "Shot",
    in_tick: 0,
    out_tick: 240,
    src_in_tick: 0,
    speed_ratio: 1,
    ...over,
  };
}

function fakeApi(tracks: Track[], clips: Clip[] = []): SequenceApi {
  return {
    listTracks: async () => tracks,
    listClips: async () => clips,
  };
}

describe("loadSequenceTracks", () => {
  it("replaces the starter timeline with the template's tracks", async () => {
    const state = createInitialState();
    const api = fakeApi([
      track({ id: "t1", name: "V1 A-Roll", track_type: "video", lane_index: 2 }),
      track({ id: "t2", name: "A1 Dialog", track_type: "audio", lane_index: 0 }),
    ]);

    await loadSequenceTracks(state, "seq-1", api);

    expect(state.timeline.tracks.map((t) => t.name)).toEqual([
      "V1 A-Roll",
      "A1 Dialog",
    ]);
    expect(state.timeline.tracks.map((t) => t.kind)).toEqual(["Video", "Audio"]);
  });

  it("leaves no placeholder clips on a fresh template project", async () => {
    const state = createInitialState();
    expect(state.timeline.tracks.flatMap((t) => t.clips)).not.toHaveLength(0);

    await loadSequenceTracks(state, "seq-1", fakeApi([track({ id: "t1" })]));

    expect(state.timeline.tracks.flatMap((t) => t.clips)).toEqual([]);
  });

  it("puts each saved clip back on its own track", async () => {
    const state = createInitialState();
    const api = fakeApi(
      [
        track({ id: "t1", name: "V1", track_type: "video" }),
        track({ id: "t2", name: "A1", track_type: "audio" }),
      ],
      [
        clip({ id: "c1", track_id: "t1", name: "Opening", in_tick: 0, out_tick: 120 }),
        clip({ id: "c2", track_id: "t2", name: "Voiceover", in_tick: 30, out_tick: 200 }),
      ],
    );

    await loadSequenceTracks(state, "seq-1", api);

    const [video, audio] = state.timeline.tracks;
    expect(video.clips).toHaveLength(1);
    expect(video.clips[0]).toMatchObject({
      label: "Opening",
      inTick: 0,
      outTick: 120,
      clipId: "c1",
    });
    expect(audio.clips).toHaveLength(1);
    expect(audio.clips[0]).toMatchObject({ label: "Voiceover", inTick: 30 });
  });

  it("skips track kinds the timeline cannot draw", async () => {
    const state = createInitialState();
    const api = fakeApi([
      track({ id: "t1", track_type: "video" }),
      track({ id: "t2", track_type: "subtitle", name: "Subs" }),
    ]);

    await loadSequenceTracks(state, "seq-1", api);

    expect(state.timeline.tracks.map((t) => t.name)).toEqual(["V1"]);
  });

  it("grows the timeline so a clip past the default end stays reachable", async () => {
    const state = createInitialState();
    const api = fakeApi(
      [track({ id: "t1" })],
      [clip({ id: "c1", track_id: "t1", in_tick: 0, out_tick: 5000 })],
    );

    await loadSequenceTracks(state, "seq-1", api);

    expect(state.timeline.durationTicks).toBeGreaterThanOrEqual(5000);
  });

  it("keeps the starter timeline when the sequence has no tracks at all", async () => {
    const state = createInitialState();

    await loadSequenceTracks(state, "seq-1", fakeApi([]));

    expect(state.timeline.tracks.length).toBeGreaterThan(0);
  });

  it("points the active track at something that exists", async () => {
    const state = createInitialState();
    const api = fakeApi([track({ id: "t1", name: "V1 Main" })]);

    await loadSequenceTracks(state, "seq-1", api);

    const ids = state.timeline.tracks.map((t) => t.id);
    expect(ids).toContain(state.ui.activeTrackId);
  });
});
