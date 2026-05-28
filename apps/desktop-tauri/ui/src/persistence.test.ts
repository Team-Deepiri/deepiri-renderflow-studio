import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { createInitialState } from "./state";
import { snapshotState } from "./ops/history";
import { saveProject, loadProject, PROJECT_STORAGE_KEY } from "./persistence";

// Stub localStorage for all tests in this file
const localStorageMock = (() => {
  let store: Record<string, string> = {};
  return {
    getItem: vi.fn((key: string) => store[key] ?? null),
    setItem: vi.fn((key: string, value: string) => { store[key] = value; }),
    removeItem: vi.fn((key: string) => { delete store[key]; }),
    clear: vi.fn(() => { store = {}; }),
  };
})();

beforeEach(() => {
  vi.stubGlobal("localStorage", localStorageMock);
  localStorageMock.clear();
  vi.clearAllMocks();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("saveProject", () => {
  it("writes to localStorage under PROJECT_STORAGE_KEY", () => {
    const state = createInitialState();
    const snap = snapshotState(state);
    saveProject("My Project", snap);
    expect(localStorageMock.setItem).toHaveBeenCalledWith(
      PROJECT_STORAGE_KEY,
      expect.any(String)
    );
  });

  it("stores projectName and savedAt", () => {
    const state = createInitialState();
    const snap = snapshotState(state);
    saveProject("My Project", snap);
    const raw = localStorageMock.setItem.mock.calls[0][1];
    const parsed = JSON.parse(raw);
    expect(parsed.projectName).toBe("My Project");
    expect(parsed.savedAt).toBeDefined();
  });

  it("stores the snapshot", () => {
    const state = createInitialState();
    const snap = snapshotState(state);
    saveProject("My Project", snap);
    const raw = localStorageMock.setItem.mock.calls[0][1];
    const parsed = JSON.parse(raw);
    expect(parsed.snapshot.timelineState.fps).toBe(24);
  });
});

describe("loadProject", () => {
  it("returns null when nothing is stored", () => {
    const result = loadProject();
    expect(result).toBeNull();
  });

  it("returns name and snapshot after save", () => {
    const state = createInitialState();
    const snap = snapshotState(state);
    saveProject("Saved Project", snap);
    // Re-wire getItem to use the stored value
    const stored = localStorageMock.setItem.mock.calls[0][1];
    localStorageMock.getItem.mockReturnValue(stored);

    const result = loadProject();
    expect(result).not.toBeNull();
    expect(result!.name).toBe("Saved Project");
    expect(result!.snapshot.timelineState.fps).toBe(24);
  });

  it("returns null when the stored JSON is corrupt", () => {
    localStorageMock.getItem.mockReturnValue("not-valid-json");
    const result = loadProject();
    expect(result).toBeNull();
  });
});
