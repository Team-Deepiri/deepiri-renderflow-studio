import type { StudioState } from "../state";
import type { Asset } from "../types";

const POLL_INTERVAL_MS = 3000;

/** Adds an asset to the list. No-op if an asset with the same id already exists. */
export function registerAsset(state: StudioState, asset: Asset): StudioState {
  if (state.assets.some((a) => a.id === asset.id)) return state;
  state.assets = [...state.assets, asset];
  return state;
}

/** Replaces an asset in the list by id. No-op if the id is not found. */
export function updateAsset(
  state: StudioState,
  assetId: string,
  updated: Asset
): StudioState {
  const idx = state.assets.findIndex((a) => a.id === assetId);
  if (idx === -1) return state;
  state.assets = [
    ...state.assets.slice(0, idx),
    updated,
    ...state.assets.slice(idx + 1),
  ];
  return state;
}

/**
 * Starts a polling interval to check proxy generation status.
 * No-op if a timer is already running or there are no pending assets.
 */
export function startProxyPolling(
  state: StudioState,
  fetchAsset: (id: string) => Promise<Asset>,
  onUpdate: (updated: Asset) => void,
  setIntervalFn: (cb: () => void, ms: number) => number = window.setInterval
): StudioState {
  if (state.proxyPollTimer !== undefined) return state;

  const hasPending = state.assets.some(
    (a) => a.meta_jsonb?.proxy_status === "pending"
  );
  if (!hasPending) return state;

  const poll = async () => {
    for (const asset of state.assets) {
      if (asset.meta_jsonb?.proxy_status !== "pending") continue;
      try {
        const refreshed = await fetchAsset(asset.id);
        onUpdate(refreshed);
      } catch {
        // Ignore individual fetch failures; will retry on next poll
      }
    }
  };

  state.proxyPollTimer = setIntervalFn(poll, POLL_INTERVAL_MS) as unknown as number;
  return state;
}

/** Stops proxy polling. No-op if no timer is running. */
export function stopProxyPolling(
  state: StudioState,
  clearIntervalFn: (id: number | undefined) => void = window.clearInterval
): StudioState {
  if (state.proxyPollTimer === undefined) return state;
  clearIntervalFn(state.proxyPollTimer);
  state.proxyPollTimer = undefined;
  return state;
}
