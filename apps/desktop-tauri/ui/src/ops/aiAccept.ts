import type { StudioState, HistoryStack } from "../state";
import type { AIJob, Asset, Clip, Track } from "../backendApi";
import type { UiClip } from "../types";
import { insertAssetIntoVideoTrack } from "./clips";

/** The backend calls insertAcceptedClip needs, injected so it stays testable. */
export type AcceptApi = {
  getAsset: (assetId: string) => Promise<Asset>;
  listTracks: (sequenceId: string) => Promise<Track[]>;
  createTrack: (
    sequenceId: string,
    trackType: string,
    laneIndex: number,
    name: string,
  ) => Promise<Track>;
  createClip: (
    sequenceId: string,
    trackId: string,
    assetId: string,
    inTick: number,
    outTick: number,
  ) => Promise<Clip>;
};

/**
 * Drops the clip an accepted AI job produced onto the timeline.
 *
 * Returns the inserted clip, or null when the job carries no asset (accept
 * failed to create one) or the project has no video track to hold it.
 */
export async function insertAcceptedClip(
  state: StudioState,
  history: HistoryStack,
  job: AIJob,
  api: AcceptApi,
): Promise<UiClip | null> {
  const assetId = job.metadata?.asset_id;
  if (!assetId) return null;

  const asset = await api.getAsset(assetId);
  const clip = insertAssetIntoVideoTrack(state, asset, history);
  if (!clip || !state.activeSequenceId) return clip;

  const trackId = await resolveVideoTrackId(state, api);
  await api.createClip(
    state.activeSequenceId,
    trackId,
    asset.id,
    clip.inTick,
    clip.outTick,
  );

  return clip;
}

/** The sequence's first video track, created on the spot if it has none. */
async function resolveVideoTrackId(
  state: StudioState,
  api: AcceptApi,
): Promise<string> {
  const sequenceId = state.activeSequenceId as string;
  const tracks = await api.listTracks(sequenceId);
  const existing = tracks.find((t) => t.track_type === "video");
  if (existing) return existing.id;

  const created = await api.createTrack(sequenceId, "video", 0, "V1");
  return created.id;
}
