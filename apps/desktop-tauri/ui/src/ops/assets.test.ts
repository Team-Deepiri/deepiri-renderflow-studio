import { describe, it, expect, vi, beforeEach } from "vitest";
import { createInitialState } from "../state";
import type { StudioState } from "../state";
import type { Asset } from "../backendApi";
import {
  registerAsset,
  updateAsset,
  startProxyPolling,
  stopProxyPolling,
} from "./assets";

let state: StudioState;

const makeAsset = (overrides: Partial<Asset> = {}): Asset => ({
  id: "asset-1",
  project_id: "proj-1",
  kind: "video",
  uri: "file:///test.mp4",
  sha256: "abc123",
  duration_ms: 5000,
    created_at: new Date().toISOString(),
  meta_jsonb: { proxy_status: "pending" },
  ...overrides,
});

beforeEach(() => {
  state = createInitialState();
});

describe("registerAsset", () => {
  it("adds a new asset to state.assets", () => {
    const result = registerAsset(state, makeAsset());
    expect(result.assets).toHaveLength(1);
    expect(result.assets[0].id).toBe("asset-1");
  });

  it("no-op if the asset id already exists", () => {
    registerAsset(state, makeAsset());
    registerAsset(state, makeAsset({ uri: "file:///other.mp4" }));
    expect(state.assets).toHaveLength(1);
  });
});

describe("updateAsset", () => {
  it("replaces an asset by id", () => {
    registerAsset(state, makeAsset());
    const updated = makeAsset({ meta_jsonb: { proxy_status: "ready" } });
    const result = updateAsset(state, "asset-1", updated);
    expect(result.assets[0].meta_jsonb?.proxy_status).toBe("ready");
  });

  it("no-op for unknown asset id", () => {
    registerAsset(state, makeAsset());
    updateAsset(state, "unknown-id", makeAsset({ id: "unknown-id" }));
    expect(state.assets).toHaveLength(1);
    expect(state.assets[0].id).toBe("asset-1");
  });
});

describe("startProxyPolling", () => {
  it("starts polling when there are pending assets", () => {
    registerAsset(
      state,
      makeAsset({ meta_jsonb: { proxy_status: "pending" } }),
    );
    const fetchAsset = vi.fn().mockResolvedValue(makeAsset());
    const onUpdate = vi.fn();
    const fakeSetInterval = vi.fn().mockReturnValue(7);
    const result = startProxyPolling(
      state,
      fetchAsset,
      onUpdate,
      fakeSetInterval,
    );
    expect(fakeSetInterval).toHaveBeenCalled();
    expect(result.proxyPollTimer).toBe(7);
  });

  it("no-op when timer is already running", () => {
    state.proxyPollTimer = 5;
    registerAsset(
      state,
      makeAsset({ meta_jsonb: { proxy_status: "pending" } }),
    );
    const fetchAsset = vi.fn();
    const onUpdate = vi.fn();
    const fakeSetInterval = vi.fn().mockReturnValue(8);
    startProxyPolling(state, fetchAsset, onUpdate, fakeSetInterval);
    expect(fakeSetInterval).not.toHaveBeenCalled();
  });

  it("no-op when there are no pending assets", () => {
    registerAsset(state, makeAsset({ meta_jsonb: { proxy_status: "ready" } }));
    const fetchAsset = vi.fn();
    const onUpdate = vi.fn();
    const fakeSetInterval = vi.fn().mockReturnValue(9);
    startProxyPolling(state, fetchAsset, onUpdate, fakeSetInterval);
    expect(fakeSetInterval).not.toHaveBeenCalled();
  });
});

describe("stopProxyPolling", () => {
  it("clears the poll timer", () => {
    state.proxyPollTimer = 7;
    const fakeClearInterval = vi.fn();
    const result = stopProxyPolling(state, fakeClearInterval);
    expect(fakeClearInterval).toHaveBeenCalledWith(7);
    expect(result.proxyPollTimer).toBeUndefined();
  });

  it("no-op when no timer is running", () => {
    const fakeClearInterval = vi.fn();
    stopProxyPolling(state, fakeClearInterval);
    expect(fakeClearInterval).not.toHaveBeenCalled();
  });
});
