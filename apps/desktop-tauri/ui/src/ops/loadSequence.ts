import type { StudioState } from "../state";
import type { Clip, Track } from "../backendApi";
import type { UiClip, UiTrack } from "../types";

/** The backend calls loadSequenceTracks needs, injected so it stays testable. */
export type SequenceApi = {
  listTracks: (sequenceId: string) => Promise<Track[]>;
  listClips: (sequenceId: string) => Promise<Clip[]>;
};

const CLIP_COLORS = [
  "#4d7dff", "#18b487", "#ff8c42", "#a855f7",
  "#ec4899", "#f59e0b", "#14b8a6", "#ef4444",
];

/** The timeline only draws video and audio lanes. */
const DRAWABLE: Record<string, UiTrack["kind"]> = {
  video: "Video",
  audio: "Audio",
};

/**
 * Replaces the starter timeline with what the sequence actually holds.
 *
 * Without this a project opens on the demo tracks and placeholder clips from
 * createInitialState(), so a template's tracks — created server-side — never
 * show up in the editor.
 *
 * Leaves the starter timeline alone when the sequence has no drawable tracks,
 * so the user still has somewhere to work.
 */
export async function loadSequenceTracks(
  state: StudioState,
  sequenceId: string,
  api: SequenceApi,
): Promise<void> {
  const [tracks, clips] = await Promise.all([
    api.listTracks(sequenceId),
    api.listClips(sequenceId),
  ]);

  const drawable = tracks.filter((t) => DRAWABLE[t.track_type]);
  if (!drawable.length) return;

  const clipsByTrack = new Map<string, Clip[]>();
  for (const c of clips) {
    const bucket = clipsByTrack.get(c.track_id);
    if (bucket) bucket.push(c);
    else clipsByTrack.set(c.track_id, [c]);
  }

  let nextId = state.nextClipId;
  state.timeline.tracks = drawable.map((t, i): UiTrack => ({
    id: nextId++,
    serverId: t.id,
    name: t.name,
    kind: DRAWABLE[t.track_type],
    lane_index: t.lane_index,
    clips: (clipsByTrack.get(t.id) ?? [])
      .sort((a, b) => a.in_tick - b.in_tick)
      .map((c): UiClip => ({
        id: nextId++,
        clipId: c.id,
        assetId: c.asset_id,
        label: c.name || c.asset_id,
        inTick: c.in_tick,
        outTick: c.out_tick,
        color: CLIP_COLORS[i % CLIP_COLORS.length],
      })),
  }));
  state.nextClipId = nextId;

  // Selection and active lane refer to the timeline we just threw away.
  state.ui.selectedClipId = null;
  state.ui.activeTrackId = state.timeline.tracks[0].id;

  const maxOut = state.timeline.tracks
    .flatMap((t) => t.clips)
    .reduce((m, c) => Math.max(m, c.outTick), 0);
  const tail = maxOut + state.timeline.fps * 2;
  if (tail > state.timeline.durationTicks) state.timeline.durationTicks = tail;
}
