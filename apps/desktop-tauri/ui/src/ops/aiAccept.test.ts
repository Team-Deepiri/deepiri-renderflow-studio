import { describe, it, expect, beforeEach } from "vitest";
import { createInitialState, createHistoryStack } from "../state";
import type { StudioState, HistoryStack } from "../state";
import type { AIJob, Asset, Clip, Track } from "../backendApi";
import { insertAcceptedClip, type AcceptApi } from "./aiAccept";

let state: StudioState;
let history: HistoryStack;

const ASSET: Asset = {
  id: "asset-ai-1",
  project_id: "proj-1",
  kind: "video",
  uri: "C:/data/render_outputs/job-1/output.mp4",
  sha256: "deadbeef",
  duration_ms: 5000, // 5s → 120 ticks at 24fps
  meta_jsonb: { name: "AI · a calm lake", proxy_status: "ready" },
  created_at: new Date().toISOString(),
};

const JOB: AIJob = {
  id: "job-1",
  project_id: "proj-1",
  mode: "scene",
  prompt: "a calm lake at sunrise",
  status: "committed",
  stages: ["preparing", "review", "committed"],
  metadata: { asset_id: ASSET.id, output_path: ASSET.uri },
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
};

/** Records every server call so tests can assert what was persisted. */
function fakeApi(overrides: Partial<AcceptApi> = {}) {
  const createdClips: Clip[] = [];
  const createdTracks: Track[] = [];
  const videoTrack: Track = {
    id: "track-v1",
    sequence_id: "seq-1",
    track_type: "video",
    lane_index: 0,
    name: "V1",
    muted: false,
    locked: false,
    solo: false,
  };

  const api: AcceptApi = {
    getAsset: async () => ASSET,
    listTracks: async () => [videoTrack],
    createTrack: async (sequenceId, trackType, laneIndex, name) => {
      const t: Track = { ...videoTrack, id: `track-new-${createdTracks.length}`, sequence_id: sequenceId, track_type: trackType as Track["track_type"], lane_index: laneIndex, name };
      createdTracks.push(t);
      return t;
    },
    createClip: async (sequenceId, trackId, assetId, inTick, outTick) => {
      const c: Clip = {
        id: `clip-${createdClips.length}`,
        track_id: trackId,
        asset_id: assetId,
        name: "clip",
        in_tick: inTick,
        out_tick: outTick,
        src_in_tick: 0,
        speed_ratio: 1.0,
      };
      createdClips.push(c);
      return c;
    },
    ...overrides,
  };
  return { api, createdClips, createdTracks, videoTrack };
}

beforeEach(() => {
  state = createInitialState();
  history = createHistoryStack();
  state.activeProjectId = "proj-1";
  state.activeSequenceId = "seq-1";
});

describe("insertAcceptedClip", () => {
  it("puts the accepted clip on the timeline at the asset's real length", async () => {
    const { api } = fakeApi();

    const clip = await insertAcceptedClip(state, history, JOB, api);

    expect(clip).not.toBeNull();
    expect(clip!.outTick - clip!.inTick).toBe(120);
    expect(state.timeline.tracks[0].clips).toContain(clip);
  });

  it("persists the clip on the sequence's video track", async () => {
    // Export renders from the server's clips, so a clip that only exists in
    // the browser is a clip that never makes it into the exported file.
    const { api, createdClips, videoTrack } = fakeApi();

    const clip = await insertAcceptedClip(state, history, JOB, api);

    expect(createdClips).toHaveLength(1);
    expect(createdClips[0]).toMatchObject({
      track_id: videoTrack.id,
      asset_id: ASSET.id,
      in_tick: clip!.inTick,
      out_tick: clip!.outTick,
    });
  });

  it("creates a video track when the sequence has none", async () => {
    const { api, createdTracks, createdClips } = fakeApi({ listTracks: async () => [] });

    await insertAcceptedClip(state, history, JOB, api);

    expect(createdTracks).toHaveLength(1);
    expect(createdTracks[0].track_type).toBe("video");
    expect(createdClips[0].track_id).toBe(createdTracks[0].id);
  });

  it("ignores audio tracks when picking where the clip goes", async () => {
    const audioOnly: Track = {
      id: "track-a1", sequence_id: "seq-1", track_type: "audio",
      lane_index: 0, name: "A1", muted: false, locked: false, solo: false,
    };
    const { api, createdTracks, createdClips } = fakeApi({ listTracks: async () => [audioOnly] });

    await insertAcceptedClip(state, history, JOB, api);

    expect(createdClips[0].track_id).toBe(createdTracks[0].id);
    expect(createdClips[0].track_id).not.toBe(audioOnly.id);
  });

  it("does nothing when accept produced no asset", async () => {
    const { api, createdClips } = fakeApi();
    const jobWithoutAsset: AIJob = { ...JOB, metadata: {} };

    const clip = await insertAcceptedClip(state, history, jobWithoutAsset, api);

    expect(clip).toBeNull();
    expect(createdClips).toHaveLength(0);
    expect(state.timeline.tracks[0].clips).toHaveLength(2); // untouched demo clips
  });

  it("keeps the clip on the local timeline when the server rejects it", async () => {
    // The generated video is real and already playable; a failed persist
    // should not make it vanish from the editor.
    const { api } = fakeApi({
      createClip: async () => { throw new Error("500 sequence not found"); },
    });

    await expect(insertAcceptedClip(state, history, JOB, api)).rejects.toThrow();
    expect(state.timeline.tracks[0].clips).toHaveLength(1);
  });
});
