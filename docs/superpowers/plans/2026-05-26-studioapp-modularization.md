# studioApp.ts Modularization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split the 1,259-line `studioApp.ts` monolith into focused, testable modules with a clean layered architecture, backed by ≥30 Vitest unit tests covering all operation edge cases.

**Architecture:** Five layers — types (shared shapes), state (single mutable object + history), operations (pure functions, fully unit-tested), renderers (DOM-only, read state), bootstrap (thin wiring). `backendApi.ts` is not modified.

**Tech Stack:** TypeScript 5.7, Vite 6, Vitest (new), vanilla DOM

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `src/types.ts` | All UI-layer TypeScript types |
| Create | `src/state.ts` | `StudioState`, `HistoryStack`, `createInitialState()` |
| Create | `src/ops/history.ts` | commit/undo/redo, snapshot/apply |
| Create | `src/ops/history.test.ts` | Vitest tests for history |
| Create | `src/ops/transport.ts` | seek/play/pause/stop/jog/shuttle/tickToTimecode |
| Create | `src/ops/transport.test.ts` | Vitest tests for transport |
| Create | `src/ops/clips.ts` | splitClip/deleteClip/moveClip/trimClip/getClipById/insertClipFromAsset |
| Create | `src/ops/clips.test.ts` | Vitest tests for clips |
| Create | `src/ops/markers.ts` | addMarker/jumpToNextMarker/removeMarker |
| Create | `src/ops/markers.test.ts` | Vitest tests for markers |
| Create | `src/ops/assets.ts` | registerAsset/updateAsset/startProxyPolling/stopProxyPolling |
| Create | `src/ops/assets.test.ts` | Vitest tests for assets |
| Create | `src/persistence.ts` | saveProject/loadProject (localStorage) |
| Create | `src/persistence.test.ts` | Vitest tests for persistence |
| Create | `src/renderer/timeline.ts` | `renderTimeline(state, root, callbacks)` |
| Create | `src/renderer/assets.ts` | `renderAssetList(assets, root, callbacks)` |
| Create | `src/renderer/inspector.ts` | `updateInspector(state, el)` |
| Create | `src/hotkeys.ts` | `registerHotkeys(dispatch)` → cleanup fn |
| Modify | `src/studioApp.ts` | Slim to ≤150 lines: DOM build + event wiring only |
| Create | `vitest.config.ts` | Vitest configuration |
| Modify | `package.json` | Add vitest + `"test"` script |
| No touch | `src/backendApi.ts` | Unchanged |

All paths are relative to `apps/desktop-tauri/ui/`.

---

## Task 0: Install Vitest and configure

**Files:**
- Modify: `apps/desktop-tauri/ui/package.json`
- Create: `apps/desktop-tauri/ui/vitest.config.ts`

- [ ] **Step 1: Install vitest**

```bash
cd apps/desktop-tauri/ui
npm install --save-dev vitest
```

Expected output: `added N packages` with vitest in devDependencies.

- [ ] **Step 2: Add test script to package.json**

Replace the `"scripts"` block in `apps/desktop-tauri/ui/package.json`:

```json
{
  "name": "deepiri-renderflow-ui",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite --port 1420 --strictPort",
    "build": "vite build",
    "preview": "vite preview",
    "test": "vitest run",
    "test:watch": "vitest"
  },
  "dependencies": {
    "@tauri-apps/api": "^2.2.0"
  },
  "devDependencies": {
    "typescript": "~5.7.0",
    "vite": "^6.0.0",
    "vitest": "^2.0.0"
  }
}
```

- [ ] **Step 3: Create vitest.config.ts**

Create `apps/desktop-tauri/ui/vitest.config.ts`:

```ts
import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
  },
});
```

- [ ] **Step 4: Verify vitest runs (no tests yet)**

```bash
cd apps/desktop-tauri/ui
npm test
```

Expected output: `No test files found` or `0 tests passed`. Not an error — just no tests yet.

---

## Task 1: Extract `types.ts`

**Files:**
- Create: `apps/desktop-tauri/ui/src/types.ts`

Note: `backendApi.ts` already exports server-side `Track`, `Clip`, and `Asset` interfaces (string UUIDs, snake_case). The UI layer has its own local types with numeric IDs and camelCase — these are named `UiClip` and `UiTrack` here to avoid shadowing the server types. `Asset` is re-exported from backendApi since it is used directly.

- [ ] **Step 1: Create types.ts**

Create `apps/desktop-tauri/ui/src/types.ts`:

```ts
export type { Asset } from "./backendApi";

export type UiClip = {
  id: number;
  serverId?: string;
  label: string;
  inTick: number;
  outTick: number;
  color: string;
};

export type UiTrack = {
  id: number;
  serverId?: string;
  name: string;
  kind: "Video" | "Audio";
  lane_index: number;
  clips: UiClip[];
};

export type TimelineState = {
  fps: number;
  durationTicks: number;
  playheadTick: number;
  tracks: UiTrack[];
};

export type TimelineUiState = {
  zoom: number;
  selectedClipId: number | null;
  activeTrackId: number | null;
  markers: number[];
};

export type TimelineSnapshot = {
  timelineState: TimelineState;
  timelineUiState: TimelineUiState;
};
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd apps/desktop-tauri/ui
npx tsc --noEmit
```

Expected: no errors.

---

## Task 2: Extract `state.ts`

**Files:**
- Create: `apps/desktop-tauri/ui/src/state.ts`

- [ ] **Step 1: Create state.ts**

Create `apps/desktop-tauri/ui/src/state.ts`:

```ts
import type { Asset } from "./backendApi";
import type {
  TimelineState,
  TimelineUiState,
  TimelineSnapshot,
  UiTrack,
} from "./types";

export type StudioState = {
  timeline: TimelineState;
  ui: TimelineUiState;
  activeProjectId: string | null;
  activeSequenceId: string | null;
  nextClipId: number;
  assets: Asset[];
  proxyPollTimer: number | undefined;
  playing: boolean;
  playTimer: number | undefined;
  lastJobId: string;
  aiVisible: boolean;
};

export type HistoryStack = {
  past: TimelineSnapshot[];
  future: TimelineSnapshot[];
  suppressHistory: boolean;
};

const DEFAULT_TRACKS: UiTrack[] = [
  {
    id: 1,
    name: "V1 Main",
    kind: "Video",
    lane_index: 1,
    clips: [
      { id: 101, label: "Intro Plate", inTick: 0, outTick: 480, color: "var(--clip-blue)" },
      { id: 102, label: "Interview A", inTick: 540, outTick: 1500, color: "var(--clip-purple)" },
    ],
  },
  {
    id: 2,
    name: "V2 Overlay",
    kind: "Video",
    lane_index: 0,
    clips: [{ id: 201, label: "Lower Third", inTick: 600, outTick: 1120, color: "var(--clip-green)" }],
  },
  {
    id: 3,
    name: "A1 Dialog",
    kind: "Audio",
    lane_index: 0,
    clips: [{ id: 301, label: "Boom", inTick: 0, outTick: 1480, color: "var(--clip-gold)" }],
  },
];

export function createInitialState(): StudioState {
  return {
    timeline: {
      fps: 24,
      durationTicks: 2400,
      playheadTick: 288,
      tracks: DEFAULT_TRACKS.map((t) => ({
        ...t,
        clips: t.clips.map((c) => ({ ...c })),
      })),
    },
    ui: {
      zoom: 1,
      selectedClipId: null,
      activeTrackId: 1,
      markers: [240, 1020, 1780],
    },
    activeProjectId: null,
    activeSequenceId: null,
    nextClipId: 1000,
    assets: [],
    proxyPollTimer: undefined,
    playing: false,
    playTimer: undefined,
    lastJobId: "",
    aiVisible: true,
  };
}

export function createHistoryStack(): HistoryStack {
  return { past: [], future: [], suppressHistory: false };
}
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd apps/desktop-tauri/ui
npx tsc --noEmit
```

Expected: no errors.

---

## Task 3: `ops/history.ts` with tests (TDD)

**Files:**
- Create: `apps/desktop-tauri/ui/src/ops/history.ts`
- Create: `apps/desktop-tauri/ui/src/ops/history.test.ts`

- [ ] **Step 1: Write the failing tests**

Create `apps/desktop-tauri/ui/src/ops/history.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import {
  snapshotState,
  applySnapshot,
  commitHistory,
  undoHistory,
  redoHistory,
} from "./history";
import { createInitialState, createHistoryStack } from "../state";

describe("snapshotState", () => {
  it("produces a deep copy — mutating original does not affect snapshot", () => {
    const state = createInitialState();
    const snap = snapshotState(state);
    state.timeline.playheadTick = 9999;
    state.timeline.tracks[0].clips[0].label = "MUTATED";
    expect(snap.timelineState.playheadTick).toBe(288);
    expect(snap.timelineState.tracks[0].clips[0].label).toBe("Intro Plate");
  });

  it("captures ui state independently", () => {
    const state = createInitialState();
    state.ui.zoom = 3.0;
    const snap = snapshotState(state);
    state.ui.zoom = 1.0;
    expect(snap.timelineUiState.zoom).toBe(3.0);
  });
});

describe("applySnapshot", () => {
  it("restores timeline state from snapshot", () => {
    const state = createInitialState();
    const snap = snapshotState(state);
    state.timeline.playheadTick = 9999;
    applySnapshot(state, snap);
    expect(state.timeline.playheadTick).toBe(288);
  });

  it("restores ui state from snapshot", () => {
    const state = createInitialState();
    state.ui.zoom = 2.5;
    const snap = snapshotState(state);
    state.ui.zoom = 1.0;
    applySnapshot(state, snap);
    expect(state.ui.zoom).toBe(2.5);
  });
});

describe("commitHistory", () => {
  it("pushes current state onto past stack", () => {
    const state = createInitialState();
    const history = createHistoryStack();
    commitHistory(state, history, "test");
    expect(history.past).toHaveLength(1);
  });

  it("clears future stack on commit", () => {
    const state = createInitialState();
    const history = createHistoryStack();
    history.future.push(snapshotState(state));
    commitHistory(state, history, "test");
    expect(history.future).toHaveLength(0);
  });

  it("caps history at 80 entries", () => {
    const state = createInitialState();
    const history = createHistoryStack();
    for (let i = 0; i < 85; i++) {
      commitHistory(state, history, `step-${i}`);
    }
    expect(history.past.length).toBeLessThanOrEqual(80);
  });

  it("does nothing when suppressHistory is true", () => {
    const state = createInitialState();
    const history = createHistoryStack();
    history.suppressHistory = true;
    commitHistory(state, history, "suppressed");
    expect(history.past).toHaveLength(0);
  });
});

describe("undoHistory", () => {
  it("restores previous state", () => {
    const state = createInitialState();
    const history = createHistoryStack();
    commitHistory(state, history, "before");
    state.timeline.playheadTick = 9999;
    undoHistory(state, history);
    expect(state.timeline.playheadTick).toBe(288);
  });

  it("pushes current state onto future stack", () => {
    const state = createInitialState();
    const history = createHistoryStack();
    commitHistory(state, history, "before");
    undoHistory(state, history);
    expect(history.future).toHaveLength(1);
  });

  it("is a no-op when past stack is empty", () => {
    const state = createInitialState();
    const history = createHistoryStack();
    state.timeline.playheadTick = 500;
    undoHistory(state, history);
    expect(state.timeline.playheadTick).toBe(500);
  });
});

describe("redoHistory", () => {
  it("reapplies undone state", () => {
    const state = createInitialState();
    const history = createHistoryStack();
    commitHistory(state, history, "before");
    state.timeline.playheadTick = 999;
    commitHistory(state, history, "after");
    undoHistory(state, history);
    undoHistory(state, history);
    redoHistory(state, history);
    expect(state.timeline.playheadTick).toBe(999);
  });

  it("is a no-op when future stack is empty", () => {
    const state = createInitialState();
    const history = createHistoryStack();
    state.timeline.playheadTick = 500;
    redoHistory(state, history);
    expect(state.timeline.playheadTick).toBe(500);
  });
});
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
cd apps/desktop-tauri/ui
npm test
```

Expected: `FAIL` — `Cannot find module './history'`.

- [ ] **Step 3: Implement ops/history.ts**

Create `apps/desktop-tauri/ui/src/ops/history.ts`:

```ts
import type { StudioState, HistoryStack } from "../state";
import type { TimelineSnapshot } from "../types";

export function snapshotState(state: StudioState): TimelineSnapshot {
  return {
    timelineState: JSON.parse(JSON.stringify(state.timeline)) as TimelineSnapshot["timelineState"],
    timelineUiState: JSON.parse(JSON.stringify(state.ui)) as TimelineSnapshot["timelineUiState"],
  };
}

export function applySnapshot(state: StudioState, snapshot: TimelineSnapshot): void {
  state.timeline.fps = snapshot.timelineState.fps;
  state.timeline.durationTicks = snapshot.timelineState.durationTicks;
  state.timeline.playheadTick = snapshot.timelineState.playheadTick;
  state.timeline.tracks = JSON.parse(JSON.stringify(snapshot.timelineState.tracks));
  state.ui.zoom = snapshot.timelineUiState.zoom;
  state.ui.selectedClipId = snapshot.timelineUiState.selectedClipId;
  state.ui.activeTrackId = snapshot.timelineUiState.activeTrackId;
  state.ui.markers = [...snapshot.timelineUiState.markers];
}

export function commitHistory(
  state: StudioState,
  history: HistoryStack,
  _label: string,
): void {
  if (history.suppressHistory) return;
  history.past.push(snapshotState(state));
  if (history.past.length > 80) history.past.shift();
  history.future.length = 0;
}

export function undoHistory(state: StudioState, history: HistoryStack): void {
  const prev = history.past.pop();
  if (!prev) return;
  history.future.push(snapshotState(state));
  history.suppressHistory = true;
  applySnapshot(state, prev);
  history.suppressHistory = false;
}

export function redoHistory(state: StudioState, history: HistoryStack): void {
  const next = history.future.pop();
  if (!next) return;
  history.past.push(snapshotState(state));
  history.suppressHistory = true;
  applySnapshot(state, next);
  history.suppressHistory = false;
}
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
cd apps/desktop-tauri/ui
npm test
```

Expected: all history tests `PASS`.

---

## Task 4: `ops/transport.ts` with tests (TDD)

**Files:**
- Create: `apps/desktop-tauri/ui/src/ops/transport.ts`
- Create: `apps/desktop-tauri/ui/src/ops/transport.test.ts`

- [ ] **Step 1: Write the failing tests**

Create `apps/desktop-tauri/ui/src/ops/transport.test.ts`:

```ts
import { describe, it, expect, vi } from "vitest";
import { seek, jog, tickToTimecode, play, pause, stop } from "./transport";
import { createInitialState, createHistoryStack } from "../state";

describe("tickToTimecode", () => {
  it("converts 288 ticks at 24fps to 00:00:12:00", () => {
    expect(tickToTimecode(288, 24)).toBe("00:00:12:00");
  });

  it("converts 0 to 00:00:00:00", () => {
    expect(tickToTimecode(0, 24)).toBe("00:00:00:00");
  });

  it("wraps frames correctly at 24fps", () => {
    // 24 frames = 1 second
    expect(tickToTimecode(24, 24)).toBe("00:00:01:00");
  });

  it("handles hours", () => {
    // 24fps * 3600s = 86400 ticks = 1 hour
    expect(tickToTimecode(86400, 24)).toBe("01:00:00:00");
  });

  it("handles negative tick as 00:00:00:00", () => {
    expect(tickToTimecode(-5, 24)).toBe("00:00:00:00");
  });
});

describe("seek", () => {
  it("sets playheadTick to given value", () => {
    const state = createInitialState();
    seek(state, 500);
    expect(state.timeline.playheadTick).toBe(500);
  });

  it("clamps to 0 when given negative tick", () => {
    const state = createInitialState();
    seek(state, -100);
    expect(state.timeline.playheadTick).toBe(0);
  });

  it("clamps to durationTicks when given value beyond duration", () => {
    const state = createInitialState();
    seek(state, 99999);
    expect(state.timeline.playheadTick).toBe(state.timeline.durationTicks);
  });

  it("allows seeking to exactly 0", () => {
    const state = createInitialState();
    seek(state, 0);
    expect(state.timeline.playheadTick).toBe(0);
  });

  it("allows seeking to exactly durationTicks", () => {
    const state = createInitialState();
    seek(state, state.timeline.durationTicks);
    expect(state.timeline.playheadTick).toBe(state.timeline.durationTicks);
  });
});

describe("jog", () => {
  it("advances playhead by 1 tick forward", () => {
    const state = createInitialState();
    state.timeline.playheadTick = 100;
    jog(state, 1);
    expect(state.timeline.playheadTick).toBe(101);
  });

  it("moves playhead back by 1 tick", () => {
    const state = createInitialState();
    state.timeline.playheadTick = 100;
    jog(state, -1);
    expect(state.timeline.playheadTick).toBe(99);
  });

  it("clamps at 0 — jog back at tick 0 stays at 0", () => {
    const state = createInitialState();
    state.timeline.playheadTick = 0;
    jog(state, -1);
    expect(state.timeline.playheadTick).toBe(0);
  });

  it("clamps at durationTicks — jog forward at end stays at end", () => {
    const state = createInitialState();
    state.timeline.playheadTick = state.timeline.durationTicks;
    jog(state, 1);
    expect(state.timeline.playheadTick).toBe(state.timeline.durationTicks);
  });
});

describe("play", () => {
  it("sets playing to true", () => {
    const state = createInitialState();
    const onTick = vi.fn().mockReturnValue(42);
    play(state, onTick);
    expect(state.playing).toBe(true);
  });

  it("stores the timer id", () => {
    const state = createInitialState();
    const onTick = vi.fn().mockReturnValue(42);
    play(state, onTick);
    expect(state.playTimer).toBe(42);
  });

  it("calls onTick with a callback and interval based on fps", () => {
    const state = createInitialState();
    state.timeline.fps = 24;
    const onTick = vi.fn().mockReturnValue(1);
    play(state, onTick);
    expect(onTick).toHaveBeenCalledWith(expect.any(Function), Math.round(1000 / 24));
  });
});

describe("pause", () => {
  it("sets playing to false", () => {
    const state = createInitialState();
    state.playing = true;
    state.playTimer = 42;
    const clearTimer = vi.fn();
    pause(state, clearTimer);
    expect(state.playing).toBe(false);
  });

  it("calls clearTimer with the timer id", () => {
    const state = createInitialState();
    state.playing = true;
    state.playTimer = 42;
    const clearTimer = vi.fn();
    pause(state, clearTimer);
    expect(clearTimer).toHaveBeenCalledWith(42);
  });

  it("sets playTimer to undefined", () => {
    const state = createInitialState();
    state.playing = true;
    state.playTimer = 42;
    pause(state, vi.fn());
    expect(state.playTimer).toBeUndefined();
  });
});

describe("stop", () => {
  it("sets playing to false and resets playhead to 0", () => {
    const state = createInitialState();
    state.playing = true;
    state.timeline.playheadTick = 500;
    stop(state, vi.fn());
    expect(state.playing).toBe(false);
    expect(state.timeline.playheadTick).toBe(0);
  });
});
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
cd apps/desktop-tauri/ui
npm test
```

Expected: `FAIL` — `Cannot find module './transport'`.

- [ ] **Step 3: Implement ops/transport.ts**

Create `apps/desktop-tauri/ui/src/ops/transport.ts`:

```ts
import type { StudioState } from "../state";

export function tickToTimecode(tick: number, fps: number): string {
  const totalFrames = Math.max(0, Math.floor(tick));
  const hours = Math.floor(totalFrames / (fps * 3600));
  const minutes = Math.floor((totalFrames % (fps * 3600)) / (fps * 60));
  const seconds = Math.floor((totalFrames % (fps * 60)) / fps);
  const frames = totalFrames % fps;
  const p2 = (v: number) => String(v).padStart(2, "0");
  return `${p2(hours)}:${p2(minutes)}:${p2(seconds)}:${p2(frames)}`;
}

export function seek(state: StudioState, tick: number): void {
  state.timeline.playheadTick = Math.max(
    0,
    Math.min(state.timeline.durationTicks, Math.round(tick)),
  );
}

export function jog(state: StudioState, direction: 1 | -1): void {
  seek(state, state.timeline.playheadTick + direction);
}

export function play(
  state: StudioState,
  onTick: (cb: () => void, ms: number) => number,
): void {
  state.playing = true;
  const interval = Math.max(15, Math.round(1000 / state.timeline.fps));
  state.playTimer = onTick(() => {
    const next = state.timeline.playheadTick + 1;
    if (next > state.timeline.durationTicks) {
      seek(state, 0);
    } else {
      seek(state, next);
    }
  }, interval);
}

export function pause(
  state: StudioState,
  clearTimer: (id: number) => void,
): void {
  if (state.playTimer !== undefined) clearTimer(state.playTimer);
  state.playTimer = undefined;
  state.playing = false;
}

export function stop(
  state: StudioState,
  clearTimer: (id: number) => void,
): void {
  pause(state, clearTimer);
  seek(state, 0);
}

export function shuttle(
  state: StudioState,
  multiplier: number,
  onTick: (cb: () => void, ms: number) => number,
  clearTimer: (id: number) => void,
): void {
  pause(state, clearTimer);
  if (multiplier === 0) return;
  state.playing = true;
  const interval = Math.max(15, Math.round(1000 / state.timeline.fps));
  state.playTimer = onTick(() => {
    const next = state.timeline.playheadTick + multiplier;
    if (next > state.timeline.durationTicks) {
      seek(state, 0);
    } else if (next < 0) {
      seek(state, state.timeline.durationTicks);
    } else {
      seek(state, next);
    }
  }, interval);
}
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
cd apps/desktop-tauri/ui
npm test
```

Expected: all transport tests `PASS`.

---

## Task 5: `ops/clips.ts` with tests (TDD)

**Files:**
- Create: `apps/desktop-tauri/ui/src/ops/clips.ts`
- Create: `apps/desktop-tauri/ui/src/ops/clips.test.ts`

- [ ] **Step 1: Write the failing tests**

Create `apps/desktop-tauri/ui/src/ops/clips.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import {
  getClipById,
  splitClip,
  deleteClip,
  moveClip,
  trimClip,
  insertClipFromAsset,
} from "./clips";
import { createInitialState, createHistoryStack } from "../state";
import type { Asset } from "../types";

const MOCK_ASSET: Asset = {
  id: "asset-1",
  project_id: "proj-1",
  kind: "video",
  uri: "/tmp/test.mp4",
  sha256: "abc",
  duration_ms: 5000,
  meta_jsonb: { name: "test.mp4" },
  created_at: "2026-01-01T00:00:00Z",
};

describe("getClipById", () => {
  it("returns clip and track when found", () => {
    const state = createInitialState();
    const result = getClipById(state, 101);
    expect(result).not.toBeNull();
    expect(result!.clip.id).toBe(101);
    expect(result!.track.id).toBe(1);
  });

  it("returns null when clip does not exist", () => {
    const state = createInitialState();
    expect(getClipById(state, 9999)).toBeNull();
  });
});

describe("splitClip", () => {
  it("splits selected clip at playhead into two clips", () => {
    const state = createInitialState();
    const history = createHistoryStack();
    state.ui.selectedClipId = 101; // inTick: 0, outTick: 480
    state.timeline.playheadTick = 240; // midpoint
    splitClip(state, history);
    const track = state.timeline.tracks[0];
    expect(track.clips).toHaveLength(3); // was 2, now 3
    const sorted = [...track.clips].sort((a, b) => a.inTick - b.inTick);
    expect(sorted[0].outTick).toBe(240);
    expect(sorted[1].inTick).toBe(240);
    expect(sorted[1].outTick).toBe(480);
  });

  it("is a no-op when playhead is at clip in-point", () => {
    const state = createInitialState();
    const history = createHistoryStack();
    state.ui.selectedClipId = 101;
    state.timeline.playheadTick = 0; // at the in-point — not inside
    const beforeCount = state.timeline.tracks[0].clips.length;
    splitClip(state, history);
    expect(state.timeline.tracks[0].clips).toHaveLength(beforeCount);
  });

  it("is a no-op when playhead is at clip out-point", () => {
    const state = createInitialState();
    const history = createHistoryStack();
    state.ui.selectedClipId = 101;
    state.timeline.playheadTick = 480; // at the out-point — not inside
    const beforeCount = state.timeline.tracks[0].clips.length;
    splitClip(state, history);
    expect(state.timeline.tracks[0].clips).toHaveLength(beforeCount);
  });

  it("is a no-op when no clip is selected", () => {
    const state = createInitialState();
    const history = createHistoryStack();
    state.ui.selectedClipId = null;
    const beforeCount = state.timeline.tracks[0].clips.length;
    splitClip(state, history);
    expect(state.timeline.tracks[0].clips).toHaveLength(beforeCount);
  });
});

describe("deleteClip", () => {
  it("removes selected clip from its track", () => {
    const state = createInitialState();
    const history = createHistoryStack();
    state.ui.selectedClipId = 101;
    deleteClip(state, history);
    const allClips = state.timeline.tracks.flatMap((t) => t.clips);
    expect(allClips.find((c) => c.id === 101)).toBeUndefined();
  });

  it("clears selectedClipId after deletion", () => {
    const state = createInitialState();
    const history = createHistoryStack();
    state.ui.selectedClipId = 101;
    deleteClip(state, history);
    expect(state.ui.selectedClipId).toBeNull();
  });

  it("is a no-op when no clip is selected", () => {
    const state = createInitialState();
    const history = createHistoryStack();
    state.ui.selectedClipId = null;
    const totalBefore = state.timeline.tracks.flatMap((t) => t.clips).length;
    deleteClip(state, history);
    expect(state.timeline.tracks.flatMap((t) => t.clips)).toHaveLength(totalBefore);
  });
});

describe("moveClip", () => {
  it("shifts clip inTick and outTick by delta", () => {
    const state = createInitialState();
    const history = createHistoryStack();
    // clip 101: inTick=0, outTick=480
    moveClip(state, 101, 100, history);
    const ref = getClipById(state, 101)!;
    expect(ref.clip.inTick).toBe(100);
    expect(ref.clip.outTick).toBe(580);
  });

  it("clamps clip to start of timeline (inTick >= 0)", () => {
    const state = createInitialState();
    const history = createHistoryStack();
    moveClip(state, 101, -500, history);
    const ref = getClipById(state, 101)!;
    expect(ref.clip.inTick).toBe(0);
  });

  it("clamps clip to end of timeline (outTick <= durationTicks)", () => {
    const state = createInitialState();
    const history = createHistoryStack();
    // clip 101: length=480. Moving +9999 should clamp outTick to 2400
    moveClip(state, 101, 9999, history);
    const ref = getClipById(state, 101)!;
    expect(ref.clip.outTick).toBe(state.timeline.durationTicks);
  });

  it("is a no-op for unknown clip id", () => {
    const state = createInitialState();
    const history = createHistoryStack();
    const before = JSON.stringify(state.timeline.tracks);
    moveClip(state, 9999, 100, history);
    expect(JSON.stringify(state.timeline.tracks)).toBe(before);
  });
});

describe("trimClip", () => {
  it("trims left edge of clip", () => {
    const state = createInitialState();
    // clip 101: inTick=0, outTick=480
    trimClip(state, 101, "left", 50);
    const ref = getClipById(state, 101)!;
    expect(ref.clip.inTick).toBe(50);
    expect(ref.clip.outTick).toBe(480); // outTick unchanged
  });

  it("trims right edge of clip", () => {
    const state = createInitialState();
    trimClip(state, 101, "right", -50);
    const ref = getClipById(state, 101)!;
    expect(ref.clip.inTick).toBe(0); // inTick unchanged
    expect(ref.clip.outTick).toBe(430);
  });

  it("enforces minimum clip length of 2 ticks when trimming left", () => {
    const state = createInitialState();
    trimClip(state, 101, "left", 479); // would leave 1 tick
    const ref = getClipById(state, 101)!;
    expect(ref.clip.outTick - ref.clip.inTick).toBeGreaterThanOrEqual(2);
  });

  it("enforces minimum clip length of 2 ticks when trimming right", () => {
    const state = createInitialState();
    trimClip(state, 101, "right", -479); // would leave 1 tick
    const ref = getClipById(state, 101)!;
    expect(ref.clip.outTick - ref.clip.inTick).toBeGreaterThanOrEqual(2);
  });
});

describe("insertClipFromAsset", () => {
  it("inserts a clip onto the active track at playhead", () => {
    const state = createInitialState();
    const history = createHistoryStack();
    state.ui.activeTrackId = 1;
    state.timeline.playheadTick = 0;
    const before = state.timeline.tracks[0].clips.length;
    insertClipFromAsset(state, MOCK_ASSET, history);
    expect(state.timeline.tracks[0].clips).toHaveLength(before + 1);
  });

  it("calculates clip duration from asset duration_ms and fps", () => {
    const state = createInitialState();
    const history = createHistoryStack();
    state.ui.activeTrackId = 1;
    state.timeline.playheadTick = 0;
    state.timeline.fps = 24;
    insertClipFromAsset(state, MOCK_ASSET, history); // 5000ms = 5s = 120 frames at 24fps
    const inserted = state.timeline.tracks[0].clips.find((c) => c.label === "test.mp4");
    expect(inserted).toBeDefined();
    expect(inserted!.outTick - inserted!.inTick).toBe(120);
  });

  it("falls back to 160 ticks when asset has no duration", () => {
    const state = createInitialState();
    const history = createHistoryStack();
    state.ui.activeTrackId = 1;
    state.timeline.playheadTick = 0;
    const nodur: Asset = { ...MOCK_ASSET, duration_ms: null };
    insertClipFromAsset(state, nodur, history);
    const inserted = state.timeline.tracks[0].clips.find((c) => c.label === "test.mp4");
    expect(inserted!.outTick - inserted!.inTick).toBe(160);
  });

  it("falls back to first track when no active track is set", () => {
    const state = createInitialState();
    const history = createHistoryStack();
    state.ui.activeTrackId = null;
    const before = state.timeline.tracks[0].clips.length;
    insertClipFromAsset(state, MOCK_ASSET, history);
    expect(state.timeline.tracks[0].clips).toHaveLength(before + 1);
  });
});
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
cd apps/desktop-tauri/ui
npm test
```

Expected: `FAIL` — `Cannot find module './clips'`.

- [ ] **Step 3: Implement ops/clips.ts**

Create `apps/desktop-tauri/ui/src/ops/clips.ts`:

```ts
import type { StudioState, HistoryStack } from "../state";
import type { UiClip, UiTrack, Asset } from "../types";
import { commitHistory } from "./history";

export function getClipById(
  state: StudioState,
  clipId: number,
): { track: UiTrack; clip: UiClip } | null {
  for (const track of state.timeline.tracks) {
    const clip = track.clips.find((c) => c.id === clipId);
    if (clip) return { track, clip };
  }
  return null;
}

export function splitClip(state: StudioState, history: HistoryStack): void {
  if (state.ui.selectedClipId == null) return;
  const ref = getClipById(state, state.ui.selectedClipId);
  if (!ref) return;
  const t = state.timeline.playheadTick;
  if (t <= ref.clip.inTick + 1 || t >= ref.clip.outTick - 1) return;
  commitHistory(state, history, "split_clip");
  const rightClip: UiClip = {
    id: state.nextClipId++,
    label: `${ref.clip.label} B`,
    inTick: t,
    outTick: ref.clip.outTick,
    color: ref.clip.color,
  };
  ref.clip.outTick = t;
  ref.clip.label = `${ref.clip.label} A`;
  ref.track.clips.push(rightClip);
  ref.track.clips.sort((a, b) => a.inTick - b.inTick);
  state.ui.selectedClipId = rightClip.id;
}

export function deleteClip(state: StudioState, history: HistoryStack): void {
  if (state.ui.selectedClipId == null) return;
  for (const track of state.timeline.tracks) {
    const idx = track.clips.findIndex((c) => c.id === state.ui.selectedClipId);
    if (idx >= 0) {
      commitHistory(state, history, "delete_clip");
      track.clips.splice(idx, 1);
      state.ui.selectedClipId = null;
      return;
    }
  }
}

export function moveClip(
  state: StudioState,
  clipId: number,
  deltaInTick: number,
  history: HistoryStack,
): void {
  const ref = getClipById(state, clipId);
  if (!ref) return;
  const length = ref.clip.outTick - ref.clip.inTick;
  let nextIn = ref.clip.inTick + deltaInTick;
  nextIn = Math.max(0, Math.min(state.timeline.durationTicks - length, nextIn));
  ref.clip.inTick = nextIn;
  ref.clip.outTick = nextIn + length;
  ref.track.clips.sort((a, b) => a.inTick - b.inTick);
}

export function trimClip(
  state: StudioState,
  clipId: number,
  side: "left" | "right",
  deltaInTick: number,
): void {
  const ref = getClipById(state, clipId);
  if (!ref) return;
  if (side === "left") {
    const maxIn = ref.clip.outTick - 2;
    ref.clip.inTick = Math.max(0, Math.min(maxIn, ref.clip.inTick + deltaInTick));
  } else {
    const minOut = ref.clip.inTick + 2;
    ref.clip.outTick = Math.max(
      minOut,
      Math.min(state.timeline.durationTicks, ref.clip.outTick + deltaInTick),
    );
  }
}

export function insertClipFromAsset(
  state: StudioState,
  asset: Asset,
  history: HistoryStack,
): void {
  const track =
    state.timeline.tracks.find((t) => t.id === state.ui.activeTrackId) ??
    state.timeline.tracks[0];
  if (!track) return;
  commitHistory(state, history, "insert_clip_from_asset");
  const name =
    asset.meta_jsonb?.name ?? asset.uri.split("/").pop() ?? asset.uri;
  const durationTicks =
    asset.duration_ms != null
      ? Math.round((asset.duration_ms / 1000) * state.timeline.fps)
      : 160;
  const inTick = Math.max(
    0,
    Math.min(
      state.timeline.durationTicks - durationTicks,
      state.timeline.playheadTick,
    ),
  );
  const newClip: UiClip = {
    id: state.nextClipId++,
    label: name,
    inTick,
    outTick: Math.min(state.timeline.durationTicks, inTick + durationTicks),
    color: asset.kind === "audio" ? "var(--clip-gold)" : "var(--clip-blue)",
  };
  track.clips.push(newClip);
  track.clips.sort((a, b) => a.inTick - b.inTick);
  state.ui.selectedClipId = newClip.id;
  state.ui.activeTrackId = track.id;
}
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
cd apps/desktop-tauri/ui
npm test
```

Expected: all clip tests `PASS`.

---

## Task 6: `ops/markers.ts` with tests (TDD)

**Files:**
- Create: `apps/desktop-tauri/ui/src/ops/markers.ts`
- Create: `apps/desktop-tauri/ui/src/ops/markers.test.ts`

- [ ] **Step 1: Write the failing tests**

Create `apps/desktop-tauri/ui/src/ops/markers.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import { addMarker, jumpToNextMarker, removeMarker } from "./markers";
import { createInitialState, createHistoryStack } from "../state";

describe("addMarker", () => {
  it("adds playhead position to markers", () => {
    const state = createInitialState();
    const history = createHistoryStack();
    state.timeline.playheadTick = 500;
    state.ui.markers = [];
    addMarker(state, history);
    expect(state.ui.markers).toContain(500);
  });

  it("deduplicates markers at same tick", () => {
    const state = createInitialState();
    const history = createHistoryStack();
    state.ui.markers = [500];
    state.timeline.playheadTick = 500;
    addMarker(state, history);
    expect(state.ui.markers.filter((m) => m === 500)).toHaveLength(1);
  });

  it("keeps markers sorted ascending after add", () => {
    const state = createInitialState();
    const history = createHistoryStack();
    state.ui.markers = [1000, 1780];
    state.timeline.playheadTick = 300;
    addMarker(state, history);
    expect(state.ui.markers[0]).toBe(300);
    expect(state.ui.markers).toEqual([...state.ui.markers].sort((a, b) => a - b));
  });
});

describe("jumpToNextMarker", () => {
  it("advances playhead to the next marker after current position", () => {
    const state = createInitialState();
    state.ui.markers = [240, 1020, 1780];
    state.timeline.playheadTick = 100;
    jumpToNextMarker(state);
    expect(state.timeline.playheadTick).toBe(240);
  });

  it("wraps to 0 when past the last marker", () => {
    const state = createInitialState();
    state.ui.markers = [240, 1020, 1780];
    state.timeline.playheadTick = 1780;
    jumpToNextMarker(state);
    expect(state.timeline.playheadTick).toBe(0);
  });

  it("is a no-op when there are no markers", () => {
    const state = createInitialState();
    state.ui.markers = [];
    state.timeline.playheadTick = 500;
    jumpToNextMarker(state);
    expect(state.timeline.playheadTick).toBe(500);
  });
});

describe("removeMarker", () => {
  it("removes a marker at the given tick", () => {
    const state = createInitialState();
    state.ui.markers = [240, 1020, 1780];
    removeMarker(state, 1020);
    expect(state.ui.markers).not.toContain(1020);
    expect(state.ui.markers).toHaveLength(2);
  });

  it("is a no-op when marker does not exist", () => {
    const state = createInitialState();
    state.ui.markers = [240, 1020];
    removeMarker(state, 9999);
    expect(state.ui.markers).toHaveLength(2);
  });
});
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
cd apps/desktop-tauri/ui
npm test
```

Expected: `FAIL` — `Cannot find module './markers'`.

- [ ] **Step 3: Implement ops/markers.ts**

Create `apps/desktop-tauri/ui/src/ops/markers.ts`:

```ts
import type { StudioState, HistoryStack } from "../state";
import { commitHistory } from "./history";

export function addMarker(state: StudioState, history: HistoryStack): void {
  commitHistory(state, history, "add_marker");
  state.ui.markers.push(state.timeline.playheadTick);
  state.ui.markers = Array.from(new Set(state.ui.markers)).sort((a, b) => a - b);
}

export function jumpToNextMarker(state: StudioState): void {
  if (state.ui.markers.length === 0) return;
  const next = state.ui.markers.find((m) => m > state.timeline.playheadTick);
  state.timeline.playheadTick = next ?? 0;
}

export function removeMarker(state: StudioState, tick: number): void {
  state.ui.markers = state.ui.markers.filter((m) => m !== tick);
}
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
cd apps/desktop-tauri/ui
npm test
```

Expected: all marker tests `PASS`.

---

## Task 7: `ops/assets.ts` with tests (TDD)

**Files:**
- Create: `apps/desktop-tauri/ui/src/ops/assets.ts`
- Create: `apps/desktop-tauri/ui/src/ops/assets.test.ts`

- [ ] **Step 1: Write the failing tests**

Create `apps/desktop-tauri/ui/src/ops/assets.test.ts`:

```ts
import { describe, it, expect, vi, beforeEach } from "vitest";
import { registerAsset, updateAsset, startProxyPolling, stopProxyPolling } from "./assets";
import { createInitialState } from "../state";
import type { Asset } from "../types";

const makeAsset = (id: string, proxyStatus: Asset["meta_jsonb"]["proxy_status"] = "ready"): Asset => ({
  id,
  project_id: "proj-1",
  kind: "video",
  uri: `/tmp/${id}.mp4`,
  sha256: "abc",
  duration_ms: 3000,
  meta_jsonb: { name: `${id}.mp4`, proxy_status: proxyStatus },
  created_at: "2026-01-01T00:00:00Z",
});

describe("registerAsset", () => {
  it("adds asset to the assets array", () => {
    const state = createInitialState();
    registerAsset(state, makeAsset("a1"));
    expect(state.assets).toHaveLength(1);
    expect(state.assets[0].id).toBe("a1");
  });

  it("does not add duplicate asset ids", () => {
    const state = createInitialState();
    registerAsset(state, makeAsset("a1"));
    registerAsset(state, makeAsset("a1"));
    expect(state.assets).toHaveLength(1);
  });
});

describe("updateAsset", () => {
  it("replaces asset in-place by id", () => {
    const state = createInitialState();
    registerAsset(state, makeAsset("a1", "pending"));
    const updated = makeAsset("a1", "ready");
    updateAsset(state, "a1", updated);
    expect(state.assets[0].meta_jsonb.proxy_status).toBe("ready");
  });

  it("is a no-op when asset id is not found", () => {
    const state = createInitialState();
    registerAsset(state, makeAsset("a1"));
    updateAsset(state, "does-not-exist", makeAsset("x"));
    expect(state.assets).toHaveLength(1);
    expect(state.assets[0].id).toBe("a1");
  });
});

describe("startProxyPolling", () => {
  it("stores timer id on state", () => {
    const state = createInitialState();
    registerAsset(state, makeAsset("a1", "pending"));
    const setIntervalMock = vi.fn().mockReturnValue(77);
    startProxyPolling(state, vi.fn(), vi.fn(), setIntervalMock);
    expect(state.proxyPollTimer).toBe(77);
  });

  it("does not start a second timer if one is already running", () => {
    const state = createInitialState();
    state.proxyPollTimer = 55;
    registerAsset(state, makeAsset("a1", "pending"));
    const setIntervalMock = vi.fn();
    startProxyPolling(state, vi.fn(), vi.fn(), setIntervalMock);
    expect(setIntervalMock).not.toHaveBeenCalled();
    expect(state.proxyPollTimer).toBe(55);
  });

  it("does not start polling when no pending assets exist", () => {
    const state = createInitialState();
    registerAsset(state, makeAsset("a1", "ready"));
    const setIntervalMock = vi.fn();
    startProxyPolling(state, vi.fn(), vi.fn(), setIntervalMock);
    expect(setIntervalMock).not.toHaveBeenCalled();
  });
});

describe("stopProxyPolling", () => {
  it("calls clearInterval with the timer id and clears it", () => {
    const state = createInitialState();
    state.proxyPollTimer = 88;
    const clearIntervalMock = vi.fn();
    stopProxyPolling(state, clearIntervalMock);
    expect(clearIntervalMock).toHaveBeenCalledWith(88);
    expect(state.proxyPollTimer).toBeUndefined();
  });

  it("is a no-op when no timer is running", () => {
    const state = createInitialState();
    const clearIntervalMock = vi.fn();
    stopProxyPolling(state, clearIntervalMock);
    expect(clearIntervalMock).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
cd apps/desktop-tauri/ui
npm test
```

Expected: `FAIL` — `Cannot find module './assets'`.

- [ ] **Step 3: Implement ops/assets.ts**

Create `apps/desktop-tauri/ui/src/ops/assets.ts`:

```ts
import type { StudioState } from "../state";
import type { Asset } from "../types";

export function registerAsset(state: StudioState, asset: Asset): void {
  if (state.assets.some((a) => a.id === asset.id)) return;
  state.assets.push(asset);
}

export function updateAsset(
  state: StudioState,
  assetId: string,
  updated: Asset,
): void {
  const idx = state.assets.findIndex((a) => a.id === assetId);
  if (idx >= 0) state.assets[idx] = updated;
}

export function startProxyPolling(
  state: StudioState,
  fetchAsset: (id: string) => Promise<Asset>,
  onUpdate: () => void,
  setIntervalFn: (cb: () => void, ms: number) => number,
): void {
  if (state.proxyPollTimer !== undefined) return;
  const hasPending = state.assets.some(
    (a) => a.meta_jsonb?.proxy_status === "pending",
  );
  if (!hasPending) return;
  state.proxyPollTimer = setIntervalFn(async () => {
    const pending = state.assets.filter(
      (a) => a.meta_jsonb?.proxy_status === "pending",
    );
    if (pending.length === 0) {
      stopProxyPolling(state, clearInterval);
      return;
    }
    let changed = false;
    for (const asset of pending) {
      try {
        const fresh = await fetchAsset(asset.id);
        if (fresh.meta_jsonb?.proxy_status !== "pending") {
          updateAsset(state, asset.id, fresh);
          changed = true;
        }
      } catch {
        // ignore transient fetch errors
      }
    }
    if (changed) onUpdate();
  }, 3000);
}

export function stopProxyPolling(
  state: StudioState,
  clearIntervalFn: (id: number) => void,
): void {
  if (state.proxyPollTimer === undefined) return;
  clearIntervalFn(state.proxyPollTimer);
  state.proxyPollTimer = undefined;
}
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
cd apps/desktop-tauri/ui
npm test
```

Expected: all asset tests `PASS`.

---

## Task 8: `persistence.ts` with tests (TDD)

**Files:**
- Create: `apps/desktop-tauri/ui/src/persistence.ts`
- Create: `apps/desktop-tauri/ui/src/persistence.test.ts`

- [ ] **Step 1: Write the failing tests**

Create `apps/desktop-tauri/ui/src/persistence.test.ts`:

```ts
import { describe, it, expect, vi, beforeEach } from "vitest";
import { saveProject, loadProject, PROJECT_STORAGE_KEY } from "./persistence";
import { createInitialState } from "./state";
import { snapshotState } from "./ops/history";

const mockStorage = (() => {
  let store: Record<string, string> = {};
  return {
    getItem: (k: string) => store[k] ?? null,
    setItem: (k: string, v: string) => { store[k] = v; },
    removeItem: (k: string) => { delete store[k]; },
    clear: () => { store = {}; },
  };
})();

beforeEach(() => {
  mockStorage.clear();
  vi.stubGlobal("localStorage", mockStorage);
});

describe("saveProject", () => {
  it("writes project name and snapshot to localStorage", () => {
    const state = createInitialState();
    const snap = snapshotState(state);
    saveProject("My Film", snap);
    const raw = mockStorage.getItem(PROJECT_STORAGE_KEY);
    expect(raw).not.toBeNull();
    const parsed = JSON.parse(raw!);
    expect(parsed.projectName).toBe("My Film");
  });

  it("includes a savedAt ISO timestamp", () => {
    const state = createInitialState();
    saveProject("Test", snapshotState(state));
    const raw = JSON.parse(mockStorage.getItem(PROJECT_STORAGE_KEY)!);
    expect(raw.savedAt).toMatch(/^\d{4}-\d{2}-\d{2}T/);
  });
});

describe("loadProject", () => {
  it("returns null when nothing is saved", () => {
    expect(loadProject()).toBeNull();
  });

  it("returns saved project name and snapshot", () => {
    const state = createInitialState();
    const snap = snapshotState(state);
    saveProject("Restored Film", snap);
    const result = loadProject();
    expect(result).not.toBeNull();
    expect(result!.name).toBe("Restored Film");
    expect(result!.snapshot.timelineState.fps).toBe(24);
  });

  it("round-trips playheadTick correctly", () => {
    const state = createInitialState();
    state.timeline.playheadTick = 999;
    const snap = snapshotState(state);
    saveProject("tick test", snap);
    const result = loadProject();
    expect(result!.snapshot.timelineState.playheadTick).toBe(999);
  });
});
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
cd apps/desktop-tauri/ui
npm test
```

Expected: `FAIL` — `Cannot find module './persistence'`.

- [ ] **Step 3: Implement persistence.ts**

Create `apps/desktop-tauri/ui/src/persistence.ts`:

```ts
import type { TimelineSnapshot } from "./types";

export const PROJECT_STORAGE_KEY = "renderflow.studio.project";

export function saveProject(name: string, snapshot: TimelineSnapshot): void {
  const payload = {
    projectName: name,
    snapshot,
    savedAt: new Date().toISOString(),
  };
  localStorage.setItem(PROJECT_STORAGE_KEY, JSON.stringify(payload));
}

export function loadProject(): { name: string; snapshot: TimelineSnapshot } | null {
  const raw = localStorage.getItem(PROJECT_STORAGE_KEY);
  if (!raw) return null;
  const parsed = JSON.parse(raw) as {
    projectName: string;
    snapshot: TimelineSnapshot;
    savedAt: string;
  };
  return { name: parsed.projectName, snapshot: parsed.snapshot };
}
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
cd apps/desktop-tauri/ui
npm test
```

Expected: all persistence tests `PASS`. Total test count should now be ≥30.

---

## Task 9: Extract renderers

**Files:**
- Create: `apps/desktop-tauri/ui/src/renderer/timeline.ts`
- Create: `apps/desktop-tauri/ui/src/renderer/assets.ts`
- Create: `apps/desktop-tauri/ui/src/renderer/inspector.ts`

These are extracted verbatim from `studioApp.ts` — no logic changes, only DOM code moved.

- [ ] **Step 1: Create renderer/timeline.ts**

Create `apps/desktop-tauri/ui/src/renderer/timeline.ts`:

```ts
import type { StudioState } from "../state";
import type { UiClip, UiTrack } from "../types";
import { tickToTimecode } from "../ops/transport";

export type TimelineCallbacks = {
  onTrackNameClick: (trackId: number) => void;
  onLaneClick: (trackId: number, ratio: number) => void;
  onClipClick: (clipId: number, trackId: number, event: MouseEvent) => void;
  onClipPointerDown: (
    clipId: number,
    trackId: number,
    mode: "move" | "trim-left" | "trim-right",
    event: PointerEvent,
  ) => void;
  getScaledDuration: () => number;
};

export function renderTimeline(
  state: StudioState,
  root: HTMLElement,
  timecodeEl: HTMLElement,
  sliderEl: HTMLInputElement,
  callbacks: TimelineCallbacks,
): void {
  const { timeline, ui } = state;
  const scaledDuration = timeline.durationTicks * ui.zoom;
  root.innerHTML = "";

  for (const track of timeline.tracks) {
    const row = document.createElement("div");
    row.className = "track-row";
    if (track.id === ui.activeTrackId) row.classList.add("active");

    const nameEl = document.createElement("div");
    nameEl.className = "track-name";
    nameEl.textContent = `${track.name} (${track.kind})`;
    nameEl.addEventListener("click", () => callbacks.onTrackNameClick(track.id));

    const lane = document.createElement("div");
    lane.className = "track-lane";
    lane.addEventListener("click", (event) => {
      const rect = lane.getBoundingClientRect();
      const ratio = (event.clientX - rect.left) / rect.width;
      callbacks.onLaneClick(track.id, ratio);
    });

    for (const markerTick of ui.markers) {
      const marker = document.createElement("div");
      marker.className = "marker";
      marker.style.left = `${((markerTick * ui.zoom) / scaledDuration) * 100}%`;
      lane.appendChild(marker);
    }

    for (const clip of track.clips) {
      const clipNode = buildClipElement(clip, track, ui.selectedClipId, ui.zoom, scaledDuration, callbacks);
      lane.appendChild(clipNode);
    }

    const playhead = document.createElement("div");
    playhead.className = "playhead";
    playhead.style.left = `${((timeline.playheadTick * ui.zoom) / scaledDuration) * 100}%`;
    lane.appendChild(playhead);

    row.append(nameEl, lane);
    root.appendChild(row);
  }

  timecodeEl.textContent = tickToTimecode(timeline.playheadTick, timeline.fps);
  sliderEl.value = String(timeline.playheadTick);
}

function buildClipElement(
  clip: UiClip,
  track: UiTrack,
  selectedClipId: number | null,
  zoom: number,
  scaledDuration: number,
  callbacks: TimelineCallbacks,
): HTMLElement {
  const clipNode = document.createElement("div");
  clipNode.className = "clip";
  if (clip.id === selectedClipId) clipNode.classList.add("selected");
  clipNode.style.left = `${((clip.inTick * zoom) / scaledDuration) * 100}%`;
  clipNode.style.width = `${(((clip.outTick - clip.inTick) * zoom) / scaledDuration) * 100}%`;
  clipNode.style.background = clip.color;
  clipNode.textContent = clip.label;
  clipNode.draggable = false;

  clipNode.addEventListener("click", (event) => {
    callbacks.onClipClick(clip.id, track.id, event);
  });

  const leftHandle = document.createElement("div");
  leftHandle.className = "trim-handle left";
  const rightHandle = document.createElement("div");
  rightHandle.className = "trim-handle right";

  const beginPointerEdit = (
    event: PointerEvent,
    mode: "move" | "trim-left" | "trim-right",
  ) => {
    event.stopPropagation();
    event.preventDefault();
    callbacks.onClipPointerDown(clip.id, track.id, mode, event);
  };

  clipNode.addEventListener("pointerdown", (e) => beginPointerEdit(e, "move"));
  leftHandle.addEventListener("pointerdown", (e) => beginPointerEdit(e, "trim-left"));
  rightHandle.addEventListener("pointerdown", (e) => beginPointerEdit(e, "trim-right"));

  clipNode.append(leftHandle, rightHandle);
  return clipNode;
}
```

- [ ] **Step 2: Create renderer/assets.ts**

Create `apps/desktop-tauri/ui/src/renderer/assets.ts`:

```ts
import type { Asset } from "../types";

export type AssetCallbacks = {
  onAssetClick: (asset: Asset) => void;
};

function fmtDuration(ms: number | null): string {
  if (ms == null) return "";
  const s = Math.floor(ms / 1000);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  if (h > 0) return `${h}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}`;
  return `${m}:${String(sec).padStart(2, "0")}`;
}

export function renderAssetList(
  assets: Asset[],
  root: HTMLElement,
  callbacks: AssetCallbacks,
): void {
  root.innerHTML = "";
  for (const asset of assets) {
    const meta = asset.meta_jsonb ?? {};
    const name = meta.name ?? asset.uri.split("/").pop() ?? asset.uri;
    const li = document.createElement("li");
    li.className = "asset-item";

    const badgeClass =
      asset.kind === "video"
        ? "badge-video"
        : asset.kind === "audio"
          ? "badge-audio"
          : "badge-image";
    const resMeta = meta.width && meta.height ? `${meta.width}×${meta.height}` : "";
    const durMeta = asset.duration_ms != null ? fmtDuration(asset.duration_ms) : "";
    const fpsMeta = meta.fps != null ? `${meta.fps.toFixed(2)} fps` : "";
    const proxyStatus = meta.proxy_status ?? "unavailable";
    const proxyLabel =
      proxyStatus === "pending"
        ? "⏳ proxy"
        : proxyStatus === "ready"
          ? "✓ proxy"
          : proxyStatus === "failed"
            ? "✗ proxy"
            : "";
    const proxyClass =
      proxyStatus === "ready"
        ? "proxy-ready"
        : proxyStatus === "failed"
          ? "proxy-failed"
          : "proxy-pending";

    li.innerHTML = `
      <div class="asset-item-name" title="${asset.uri}">${name}</div>
      <div class="asset-item-meta">
        <span class="asset-badge ${badgeClass}">${asset.kind}</span>
        ${durMeta ? `<span>${durMeta}</span>` : ""}
        ${resMeta ? `<span>${resMeta}</span>` : ""}
        ${fpsMeta ? `<span>${fpsMeta}</span>` : ""}
        ${proxyLabel ? `<span class="${proxyClass}">${proxyLabel}</span>` : ""}
      </div>
    `;

    li.addEventListener("click", () => callbacks.onAssetClick(asset));
    root.appendChild(li);
  }
}
```

- [ ] **Step 3: Create renderer/inspector.ts**

Create `apps/desktop-tauri/ui/src/renderer/inspector.ts`:

```ts
import type { StudioState } from "../state";
import { getClipById } from "../ops/clips";

export function updateInspector(state: StudioState, el: HTMLElement): void {
  if (state.ui.selectedClipId == null) {
    el.textContent = "No clip selected.";
    return;
  }
  const ref = getClipById(state, state.ui.selectedClipId);
  if (!ref) {
    el.textContent = "Selected clip is no longer available.";
    return;
  }
  const duration = ref.clip.outTick - ref.clip.inTick;
  el.textContent = `${ref.track.name}: ${ref.clip.label} | in ${ref.clip.inTick} | out ${ref.clip.outTick} | len ${duration}f`;
}
```

- [ ] **Step 4: Verify TypeScript compiles**

```bash
cd apps/desktop-tauri/ui
npx tsc --noEmit
```

Expected: no errors.

---

## Task 10: Extract `hotkeys.ts`

**Files:**
- Create: `apps/desktop-tauri/ui/src/hotkeys.ts`

- [ ] **Step 1: Create hotkeys.ts**

Create `apps/desktop-tauri/ui/src/hotkeys.ts`:

```ts
export type HotkeyDispatch = {
  jogBack: () => void;
  jogForward: () => void;
  shuttleBack: () => void;
  shuttleStop: () => void;
  shuttleForward: () => void;
  addMarker: () => void;
  splitClip: () => void;
  deleteClip: () => void;
  undo: () => void;
  redo: () => void;
};

export function registerHotkeys(dispatch: HotkeyDispatch): () => void {
  function onKeyDown(event: KeyboardEvent): void {
    const tag = (event.target as HTMLElement)?.tagName;
    if (tag === "TEXTAREA" || tag === "INPUT") return;

    switch (event.key) {
      case "ArrowLeft":
        event.preventDefault();
        dispatch.jogBack();
        break;
      case "ArrowRight":
        event.preventDefault();
        dispatch.jogForward();
        break;
      case "j":
      case "J":
        event.preventDefault();
        dispatch.shuttleBack();
        break;
      case "k":
      case "K":
        event.preventDefault();
        dispatch.shuttleStop();
        break;
      case "l":
      case "L":
        event.preventDefault();
        dispatch.shuttleForward();
        break;
      case "m":
      case "M":
        event.preventDefault();
        dispatch.addMarker();
        break;
      case "s":
      case "S":
        event.preventDefault();
        dispatch.splitClip();
        break;
      case "Delete":
      case "Backspace":
        event.preventDefault();
        dispatch.deleteClip();
        break;
      default:
        if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "z" && !event.shiftKey) {
          event.preventDefault();
          dispatch.undo();
        } else if (
          ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "y") ||
          ((event.ctrlKey || event.metaKey) && event.shiftKey && event.key.toLowerCase() === "z")
        ) {
          event.preventDefault();
          dispatch.redo();
        }
    }
  }

  window.addEventListener("keydown", onKeyDown);
  return () => window.removeEventListener("keydown", onKeyDown);
}
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd apps/desktop-tauri/ui
npx tsc --noEmit
```

Expected: no errors.

---

## Task 11: Rewrite `studioApp.ts` as thin bootstrap

**Files:**
- Modify: `apps/desktop-tauri/ui/src/studioApp.ts`

This is the final step. Replace the entire file with a thin bootstrap that wires all the extracted modules together. The DOM structure and CSS stay identical to the original.

- [ ] **Step 1: Replace studioApp.ts**

Overwrite `apps/desktop-tauri/ui/src/studioApp.ts` with:

```ts
import {
  orchestratorHealth,
  orchestratorListProjects,
  orchestratorCreateProject,
  orchestratorCreateSequence,
  orchestratorCreateTrack,
  orchestratorCreateClip,
  orchestratorListSequences,
  orchestratorListTracks,
  orchestratorListClips,
  submitAiJob,
  getAiJob,
  probeMedia,
  importMedia,
  listProjectAssets,
  getAsset,
  vulkanDiscover,
  timelineResolveActive,
} from "./backendApi";
import { createInitialState, createHistoryStack } from "./state";
import { commitHistory, undoHistory, redoHistory, snapshotState, applySnapshot } from "./ops/history";
import { seek, jog, play, pause, stop, shuttle } from "./ops/transport";
import { splitClip, deleteClip, moveClip, trimClip, insertClipFromAsset, getClipById } from "./ops/clips";
import { addMarker, jumpToNextMarker } from "./ops/markers";
import { registerAsset, updateAsset, startProxyPolling, stopProxyPolling } from "./ops/assets";
import { saveProject, loadProject } from "./persistence";
import { renderTimeline } from "./renderer/timeline";
import { renderAssetList } from "./renderer/assets";
import { updateInspector } from "./renderer/inspector";
import { registerHotkeys } from "./hotkeys";

const PLACEHOLDER_ASSET_ID = "00000000-0000-0000-0000-000000000001";

export function bootstrapStudioApp(): void {
  const app = document.querySelector<HTMLDivElement>("#app");
  if (!app) throw new Error("Missing #app root element");

  // ── DOM + CSS ──────────────────────────────────────────────────────────────
  app.innerHTML = buildDom();
  document.head.appendChild(buildStyle());

  // ── Element refs ───────────────────────────────────────────────────────────
  const out = document.querySelector<HTMLPreElement>("#out")!;
  const workspace = document.querySelector<HTMLDivElement>("#workspace")!;
  const aiPanel = document.querySelector<HTMLDivElement>("#ai-panel")!;
  const timecodeEl = document.querySelector<HTMLSpanElement>("#timecode")!;
  const slider = document.querySelector<HTMLInputElement>("#playhead-slider")!;
  const timelineGrid = document.querySelector<HTMLDivElement>("#timeline-grid")!;
  const assetListEl = document.querySelector<HTMLUListElement>("#asset-list")!;
  const fpsInput = document.querySelector<HTMLInputElement>("#project-fps")!;
  const aiPrompt = document.querySelector<HTMLTextAreaElement>("#ai-prompt")!;
  const inspectorEl = document.querySelector<HTMLDivElement>("#inspector")!;
  const zoomInput = document.querySelector<HTMLInputElement>("#timeline-zoom")!;

  // ── State ──────────────────────────────────────────────────────────────────
  const state = createInitialState();
  const history = createHistoryStack();

  // ── Render helpers ─────────────────────────────────────────────────────────
  function repaint(): void {
    renderTimeline(state, timelineGrid, timecodeEl, slider, {
      onTrackNameClick: (trackId) => {
        state.ui.activeTrackId = trackId;
        repaint();
      },
      onLaneClick: (trackId, ratio) => {
        const scaledDuration = state.timeline.durationTicks * state.ui.zoom;
        seek(state, (ratio * scaledDuration) / state.ui.zoom);
        state.ui.activeTrackId = trackId;
        repaint();
      },
      onClipClick: (clipId, trackId, event) => {
        event.stopPropagation();
        state.ui.selectedClipId = clipId;
        state.ui.activeTrackId = trackId;
        updateInspector(state, inspectorEl);
        repaint();
      },
      onClipPointerDown: (clipId, trackId, mode, event) => {
        event.stopPropagation();
        event.preventDefault();
        state.ui.selectedClipId = clipId;
        state.ui.activeTrackId = trackId;
        repaint();
        commitHistory(state, history, mode);
        const startX = event.clientX;
        const ref = getClipById(state, clipId)!;
        const startIn = ref.clip.inTick;
        const startOut = ref.clip.outTick;
        const laneEl = (event.target as HTMLElement).closest<HTMLElement>(".track-lane");
        const laneWidth = Math.max(1, laneEl?.getBoundingClientRect().width ?? 1);
        const scaledDuration = state.timeline.durationTicks * state.ui.zoom;
        const ticksPerPx = (scaledDuration / state.ui.zoom) / laneWidth;
        const onMove = (moveEvent: PointerEvent) => {
          const deltaTick = Math.round((moveEvent.clientX - startX) * ticksPerPx);
          if (mode === "move") {
            moveClip(state, clipId, deltaTick - (ref.clip.inTick - startIn), history);
            // reset to start position before applying new delta
            ref.clip.inTick = startIn;
            ref.clip.outTick = startOut;
            moveClip(state, clipId, deltaTick, history);
          } else {
            trimClip(state, clipId, mode === "trim-left" ? "left" : "right", deltaTick);
          }
          repaint();
        };
        const onUp = () => {
          window.removeEventListener("pointermove", onMove);
          window.removeEventListener("pointerup", onUp);
          updateInspector(state, inspectorEl);
        };
        window.addEventListener("pointermove", onMove);
        window.addEventListener("pointerup", onUp);
      },
      getScaledDuration: () => state.timeline.durationTicks * state.ui.zoom,
    });
    renderAssetList(state.assets, assetListEl, {
      onAssetClick: (asset) => insertClipFromAsset(state, asset, history),
    });
    updateInspector(state, inspectorEl);
    slider.max = String(state.timeline.durationTicks);
  }

  function writeOutput(value: unknown): void {
    out.textContent = typeof value === "string" ? value : JSON.stringify(value, null, 2);
  }

  // ── Button wiring ──────────────────────────────────────────────────────────
  document.querySelector("#btn-toggle-ai")!.addEventListener("click", () => {
    state.aiVisible = !state.aiVisible;
    aiPanel.style.display = state.aiVisible ? "block" : "none";
    workspace.classList.toggle("ai-hidden", !state.aiVisible);
    (document.querySelector("#btn-toggle-ai") as HTMLButtonElement).textContent =
      state.aiVisible ? "Hide AI Panel" : "Show AI Panel";
  });

  document.querySelector("#btn-toggle-theme")!.addEventListener("click", () => {
    document.body.style.filter = document.body.style.filter ? "" : "hue-rotate(18deg) saturate(1.05)";
  });

  document.querySelector("#btn-undo")!.addEventListener("click", () => {
    undoHistory(state, history);
    fpsInput.value = String(state.timeline.fps);
    zoomInput.value = String(state.ui.zoom);
    repaint();
  });

  document.querySelector("#btn-redo")!.addEventListener("click", () => {
    redoHistory(state, history);
    fpsInput.value = String(state.timeline.fps);
    zoomInput.value = String(state.ui.zoom);
    repaint();
  });

  document.querySelector("#btn-add-marker")!.addEventListener("click", () => {
    addMarker(state, history);
    repaint();
  });

  document.querySelector("#btn-jump-next-marker")!.addEventListener("click", () => {
    jumpToNextMarker(state);
    repaint();
  });

  document.querySelector("#btn-split-clip")!.addEventListener("click", () => {
    splitClip(state, history);
    repaint();
  });

  document.querySelector("#btn-delete-clip")!.addEventListener("click", () => {
    deleteClip(state, history);
    repaint();
  });

  document.querySelector("#btn-back")!.addEventListener("click", () => {
    jog(state, -1);
    repaint();
  });

  document.querySelector("#btn-forward")!.addEventListener("click", () => {
    jog(state, 1);
    repaint();
  });

  document.querySelector("#btn-play")!.addEventListener("click", () => {
    if (state.playing) {
      pause(state, window.clearInterval.bind(window));
      (document.querySelector("#btn-play") as HTMLButtonElement).textContent = "Play";
    } else {
      play(state, window.setInterval.bind(window));
      (document.querySelector("#btn-play") as HTMLButtonElement).textContent = "Pause";
    }
  });

  slider.addEventListener("input", () => {
    seek(state, Number(slider.value));
    repaint();
  });

  fpsInput.addEventListener("change", () => {
    const next = Number(fpsInput.value);
    if (Number.isFinite(next) && next > 0 && next <= 120) {
      state.timeline.fps = Math.floor(next);
      repaint();
    } else {
      fpsInput.value = String(state.timeline.fps);
    }
  });

  zoomInput.addEventListener("input", () => {
    commitHistory(state, history, "zoom_change");
    state.ui.zoom = Number(zoomInput.value);
    repaint();
  });

  document.querySelector("#btn-save-project")!.addEventListener("click", async () => {
    if (!state.activeProjectId || !state.activeSequenceId) {
      const name = (document.querySelector<HTMLInputElement>("#project-name")?.value ?? "Untitled").trim();
      saveProject(name, snapshotState(state));
      writeOutput({ action: "save_local", name });
      return;
    }
    try {
      for (const track of state.timeline.tracks) {
        if (!track.serverId) {
          const t = await orchestratorCreateTrack(state.activeSequenceId, track.kind.toLowerCase(), track.lane_index, track.name);
          track.serverId = t.id;
        }
        for (const clip of track.clips) {
          if (!clip.serverId && track.serverId) {
            const c = await orchestratorCreateClip(state.activeSequenceId, track.serverId, PLACEHOLDER_ASSET_ID, clip.inTick, clip.outTick);
            clip.serverId = c.id;
          }
        }
      }
      writeOutput({ action: "save_project", projectId: state.activeProjectId });
    } catch (e) {
      writeOutput({ action: "save_error", error: String(e) });
    }
  });

  document.querySelector("#btn-load-project")!.addEventListener("click", async () => {
    // Try server first, fall back to localStorage
    try {
      const result = await orchestratorListProjects();
      if (!result.items.length) {
        const local = loadProject();
        if (local) {
          commitHistory(state, history, "before_load_project");
          applySnapshot(state, local.snapshot);
          (document.querySelector<HTMLInputElement>("#project-name")!).value = local.name;
          fpsInput.value = String(state.timeline.fps);
          zoomInput.value = String(state.ui.zoom);
          repaint();
          writeOutput({ action: "load_local", name: local.name });
        } else {
          writeOutput("No projects found.");
        }
        return;
      }
      const project = result.items[0];
      state.activeProjectId = project.id;
      const sequences = await orchestratorListSequences(project.id) as { id: string }[];
      if (!sequences.length) { writeOutput("Project has no sequences."); return; }
      state.activeSequenceId = sequences[0].id;
      const tracks = await orchestratorListTracks(state.activeSequenceId);
      const clips = await orchestratorListClips(state.activeSequenceId);
      let nextId = Date.now();
      state.timeline.tracks = tracks.map((t) => ({
        id: nextId++,
        serverId: t.id,
        name: t.name,
        kind: (t.track_type === "audio" ? "Audio" : "Video") as "Video" | "Audio",
        lane_index: t.lane_index,
        clips: (clips as { track_id: string; id: string; name?: string; in_tick: number; out_tick: number }[])
          .filter((c) => c.track_id === t.id)
          .map((c) => ({ id: nextId++, serverId: c.id, label: c.name || "Clip", inTick: c.in_tick, outTick: c.out_tick, color: "var(--clip-blue)" })),
      }));
      state.ui.activeTrackId = state.timeline.tracks[0]?.id ?? null;
      (document.querySelector<HTMLInputElement>("#project-name")!).value = project.name;
      try {
        const assets = await listProjectAssets(project.id);
        state.assets = [];
        for (const a of assets) registerAsset(state, a);
        if (state.assets.some((a) => a.meta_jsonb?.proxy_status === "pending")) {
          startProxyPolling(state, getAsset, repaint, window.setInterval.bind(window));
        }
      } catch { /* orchestrator may not have assets yet */ }
      repaint();
      writeOutput({ action: "load_project", projectId: project.id });
    } catch (e) {
      writeOutput({ action: "load_error", error: String(e) });
    }
  });

  document.querySelector("#btn-new-project")!.addEventListener("click", async () => {
    commitHistory(state, history, "new_project");
    const projectName = `Untitled ${new Date().toLocaleTimeString()}`;
    (document.querySelector<HTMLInputElement>("#project-name")!).value = projectName;
    try {
      const project = await orchestratorCreateProject(projectName);
      state.activeProjectId = project.id;
      const seq = await orchestratorCreateSequence(project.id, "Main Sequence");
      state.activeSequenceId = seq.id;
      const v1Server = await orchestratorCreateTrack(seq.id, "video", 0, "V1");
      const a1Server = await orchestratorCreateTrack(seq.id, "audio", 0, "A1");
      const v1Id = state.nextClipId++;
      const a1Id = state.nextClipId++;
      state.timeline.tracks = [
        { id: v1Id, serverId: v1Server.id, name: "V1", kind: "Video", lane_index: 0, clips: [] },
        { id: a1Id, serverId: a1Server.id, name: "A1", kind: "Audio", lane_index: 0, clips: [] },
      ];
      state.timeline.playheadTick = 0;
      state.ui.selectedClipId = null;
      state.ui.activeTrackId = v1Id;
      state.ui.markers = [];
      state.assets = [];
      repaint();
      writeOutput({ action: "new_project", projectId: project.id, sequenceId: seq.id });
    } catch (e) {
      writeOutput({ action: "new_project_error", error: String(e) });
      repaint();
    }
  });

  document.querySelector("#btn-health")!.addEventListener("click", async () => {
    try { writeOutput(await orchestratorHealth()); } catch (e) { writeOutput(e); }
  });

  document.querySelector("#btn-projects")!.addEventListener("click", async () => {
    try { writeOutput(await orchestratorListProjects()); } catch (e) { writeOutput(e); }
  });

  document.querySelector("#btn-vulkan")!.addEventListener("click", async () => {
    try { writeOutput(await vulkanDiscover()); } catch (e) { writeOutput(e); }
  });

  document.querySelector("#btn-timeline")!.addEventListener("click", async () => {
    try {
      const r = await timelineResolveActive({
        playhead_tick: state.timeline.playheadTick,
        sequence: {
          tracks: state.timeline.tracks.map((t) => ({ id: t.id, kind: t.kind, lane_index: t.lane_index, name: t.name })),
          clips: state.timeline.tracks.flatMap((t) =>
            t.clips.map((c) => ({ id: c.id, track_id: t.id, asset_id: c.id + 9000, span: { in_tick: c.inTick, out_tick: c.outTick }, src_in_tick: 0 })),
          ),
        },
      });
      writeOutput(r);
    } catch (e) { writeOutput(e); }
  });

  document.querySelector("#btn-probe")!.addEventListener("click", async () => {
    const path = window.prompt("Path or URL to probe (ffprobe):", "/tmp/sample.mp4");
    if (!path) return;
    try { writeOutput(await probeMedia(path)); } catch (e) { writeOutput(e); }
  });

  document.querySelector("#btn-submit-job")!.addEventListener("click", async () => {
    const prompt = aiPrompt.value.trim();
    if (!prompt) { writeOutput("Enter an AI prompt first."); return; }
    try {
      const result = await submitAiJob(prompt);
      state.lastJobId = result.job_id;
      writeOutput({ submitted: result, hint: "Use Refresh Job to poll status." });
    } catch (e) { writeOutput(e); }
  });

  document.querySelector("#btn-refresh-job")!.addEventListener("click", async () => {
    if (!state.lastJobId) { writeOutput("No known job id yet. Submit a job first."); return; }
    try { writeOutput(await getAiJob(state.lastJobId)); } catch (e) { writeOutput(e); }
  });

  document.querySelector("#btn-import-media")!.addEventListener("click", async () => {
    const path = window.prompt("Absolute path to media file:");
    if (!path?.trim()) return;
    await handleImportFile(path.trim());
  });

  async function handleImportFile(filePath: string): Promise<void> {
    if (!state.activeProjectId) { writeOutput("Create or load a project first, then import media."); return; }
    writeOutput(`Importing: ${filePath}`);
    try {
      const asset = await importMedia(state.activeProjectId, filePath);
      registerAsset(state, asset);
      repaint();
      writeOutput({ action: "import_asset", id: asset.id, kind: asset.kind });
      if (asset.meta_jsonb?.proxy_status === "pending") {
        startProxyPolling(state, getAsset, repaint, window.setInterval.bind(window));
      }
    } catch (e) {
      writeOutput({ action: "import_error", error: String(e) });
    }
  }

  const dropZone = document.querySelector<HTMLDivElement>("#drop-zone")!;
  dropZone.addEventListener("dragover", (e) => { e.preventDefault(); dropZone.classList.add("drag-over"); });
  dropZone.addEventListener("dragleave", () => dropZone.classList.remove("drag-over"));
  dropZone.addEventListener("drop", (e) => {
    e.preventDefault();
    dropZone.classList.remove("drag-over");
    const files = Array.from(e.dataTransfer?.files ?? []);
    for (const file of files) handleImportFile((file as File & { path?: string }).path ?? file.name);
  });

  (async () => {
    try {
      const { getCurrentWebview } = await import("@tauri-apps/api/webview");
      await getCurrentWebview().onDragDropEvent(async (event) => {
        if (event.payload.type === "over") { dropZone.classList.add("drag-over"); return; }
        if (event.payload.type === "leave") { dropZone.classList.remove("drag-over"); return; }
        if (event.payload.type === "drop") {
          dropZone.classList.remove("drag-over");
          for (const path of event.payload.paths) await handleImportFile(path);
        }
      });
    } catch { /* not in Tauri */ }
  })();

  // ── Hotkeys ────────────────────────────────────────────────────────────────
  registerHotkeys({
    jogBack: () => { jog(state, -1); repaint(); },
    jogForward: () => { jog(state, 1); repaint(); },
    shuttleBack: () => { shuttle(state, -2, window.setInterval.bind(window), window.clearInterval.bind(window)); },
    shuttleStop: () => { pause(state, window.clearInterval.bind(window)); (document.querySelector("#btn-play") as HTMLButtonElement).textContent = "Play"; },
    shuttleForward: () => { shuttle(state, 2, window.setInterval.bind(window), window.clearInterval.bind(window)); },
    addMarker: () => { addMarker(state, history); repaint(); },
    splitClip: () => { splitClip(state, history); repaint(); },
    deleteClip: () => { deleteClip(state, history); repaint(); },
    undo: () => { undoHistory(state, history); fpsInput.value = String(state.timeline.fps); zoomInput.value = String(state.ui.zoom); repaint(); },
    redo: () => { redoHistory(state, history); fpsInput.value = String(state.timeline.fps); zoomInput.value = String(state.ui.zoom); repaint(); },
  });

  // ── Initial render ─────────────────────────────────────────────────────────
  fpsInput.value = String(state.timeline.fps);
  zoomInput.value = String(state.ui.zoom);
  repaint();
}

// ── DOM template ──────────────────────────────────────────────────────────────
function buildDom(): string {
  return `
  <div class="studio">
    <header class="topbar">
      <div class="brand">Deepiri Renderflow Studio</div>
      <div class="toolbar">
        <button class="btn subtle" id="btn-toggle-ai" type="button">Hide AI Panel</button>
        <button class="btn subtle" id="btn-toggle-theme" type="button">Theme</button>
        <button class="btn subtle" id="btn-undo" type="button">Undo</button>
        <button class="btn subtle" id="btn-redo" type="button">Redo</button>
        <button class="btn subtle" id="btn-load-project" type="button">Load</button>
        <button class="btn" id="btn-new-project" type="button">New Project</button>
        <button class="btn" id="btn-save-project" type="button">Save</button>
      </div>
    </header>
    <div class="workspace" id="workspace">
      <aside class="panel left">
        <div class="panel-title">Project Explorer</div>
        <div class="project-meta">
          <label>Name <input id="project-name" value="Brand Film v01" /></label>
          <label>FPS <input id="project-fps" type="number" min="1" max="120" value="24" /></label>
          <label>Zoom <input id="timeline-zoom" type="range" min="0.8" max="3.4" step="0.1" value="1" /></label>
        </div>
        <div class="quick-actions">
          <button class="btn subtle" id="btn-add-marker" type="button">Add Marker @ Playhead</button>
          <button class="btn subtle" id="btn-jump-next-marker" type="button">Next Marker</button>
        </div>
        <div class="asset-section">
          <h4>Assets</h4>
          <div id="drop-zone" class="drop-zone">Drop media files here</div>
          <ul id="asset-list" class="asset-list"></ul>
          <div class="asset-actions">
            <button class="btn narrow" id="btn-import-media" type="button">Import Media</button>
            <button class="btn narrow subtle" id="btn-probe" type="button">Probe</button>
          </div>
        </div>
      </aside>
      <main class="center">
        <section class="monitor">
          <div class="monitor-head">
            <h3>Program Monitor</h3>
            <div class="transport">
              <button class="btn icon" id="btn-back" type="button">-1f</button>
              <button class="btn icon" id="btn-play" type="button">Play</button>
              <button class="btn icon" id="btn-forward" type="button">+1f</button>
              <span class="timecode" id="timecode">00:00:12:00</span>
            </div>
          </div>
          <div id="preview" class="preview">
            <div class="preview-overlay">
              <span>Vulkan preview surface placeholder</span>
              <button class="btn narrow" id="btn-vulkan" type="button">Query Vulkan Devices</button>
            </div>
          </div>
        </section>
        <section class="timeline">
          <div class="timeline-head">
            <h3>Timeline</h3>
            <div class="timeline-controls">
              <input id="playhead-slider" type="range" min="0" max="2400" value="288" />
              <button class="btn subtle" id="btn-split-clip" type="button">Split</button>
              <button class="btn subtle" id="btn-delete-clip" type="button">Delete</button>
            </div>
          </div>
          <div class="hint">Hotkeys: J/K/L shuttle, Arrow keys frame-step, M marker, S split, Del delete</div>
          <div id="timeline-grid" class="timeline-grid"></div>
        </section>
      </main>
      <aside class="panel right" id="ai-panel">
        <div class="panel-title">AI Copilot</div>
        <div class="ai-mode">Manual path parity: every action has a no-AI equivalent.</div>
        <textarea id="ai-prompt" rows="4" placeholder="Describe a scene, shot list, or generation request..."></textarea>
        <div class="stack">
          <button class="btn" id="btn-health" type="button">Orchestrator Health</button>
          <button class="btn" id="btn-projects" type="button">List Projects</button>
          <button class="btn" id="btn-submit-job" type="button">Submit AI Job</button>
          <button class="btn" id="btn-refresh-job" type="button">Refresh Job</button>
          <button class="btn" id="btn-timeline" type="button">Resolve Active Clips (native)</button>
        </div>
        <div id="inspector" class="inspector">No clip selected.</div>
        <pre id="out"></pre>
      </aside>
    </div>
  </div>`;
}

function buildStyle(): HTMLStyleElement {
  const style = document.createElement("style");
  style.textContent = `
  :root {
    --bg: #111319; --bg-soft: #181c24; --border: #2a3140; --text: #f3f6ff;
    --text-dim: #a8b2c7; --accent: #4d7dff; --danger: #ff4e75;
    --clip-blue: #2e78ff; --clip-purple: #8a54f5; --clip-green: #18b487; --clip-gold: #cb9342;
  }
  body { margin:0; font-family:"Segoe UI","Inter",system-ui,sans-serif; background:radial-gradient(circle at 10% 10%,#202a43 0%,#111319 45%); color:var(--text); }
  .studio { min-height:100vh; }
  .topbar { border-bottom:1px solid var(--border); display:flex; align-items:center; justify-content:space-between; padding:10px 14px; background:rgba(17,19,25,0.85); backdrop-filter:blur(6px); }
  .brand { font-size:15px; font-weight:600; letter-spacing:0.2px; }
  .toolbar { display:flex; gap:8px; }
  .workspace { display:grid; grid-template-columns:280px 1fr 320px; min-height:calc(100vh - 57px); }
  .workspace.ai-hidden { grid-template-columns:280px 1fr; }
  .panel,.center { border-right:1px solid var(--border); background:rgba(20,24,33,0.93); }
  .panel { padding:12px; }
  .panel-title { font-size:13px; text-transform:uppercase; letter-spacing:0.8px; color:var(--text-dim); margin-bottom:10px; }
  .project-meta { display:grid; gap:8px; margin-bottom:12px; }
  .project-meta label { font-size:12px; color:var(--text-dim); display:grid; gap:4px; }
  .quick-actions { display:grid; gap:6px; margin-bottom:12px; }
  .project-meta input,textarea { background:#0f131b; border:1px solid var(--border); color:var(--text); border-radius:6px; padding:8px; }
  .asset-list { margin:8px 0 12px; padding-left:18px; color:var(--text-dim); }
  .asset-list li { margin:4px 0; }
  .center { display:grid; grid-template-rows:1fr 290px; }
  .monitor { padding:12px; border-bottom:1px solid var(--border); display:grid; grid-template-rows:auto 1fr; }
  .monitor-head,.timeline-head { display:flex; justify-content:space-between; align-items:center; gap:10px; }
  .monitor-head h3,.timeline-head h3 { margin:0; font-size:14px; }
  .preview { margin-top:10px; border:1px dashed #536180; border-radius:10px; display:grid; place-items:center; background:linear-gradient(145deg,#0d1119,#0a0c12); }
  .preview-overlay { text-align:center; display:grid; gap:10px; color:var(--text-dim); font-size:12px; }
  .timeline { padding:12px; background:#111621; }
  .timeline-controls { display:flex; align-items:center; gap:6px; width:64%; }
  .timeline-grid { margin-top:10px; border:1px solid var(--border); border-radius:8px; overflow:hidden; background:#0d1119; user-select:none; }
  .hint { font-size:11px; color:var(--text-dim); margin-top:6px; }
  .track-row { display:grid; grid-template-columns:110px 1fr; min-height:46px; border-bottom:1px solid #1f2736; }
  .track-name { border-right:1px solid #1f2736; padding:10px 8px; font-size:12px; color:var(--text-dim); }
  .track-lane { position:relative; }
  .marker { position:absolute; top:0; bottom:0; width:1px; background:rgba(255,219,120,0.9); pointer-events:none; }
  .clip { position:absolute; top:8px; bottom:8px; border-radius:6px; padding:6px 8px; font-size:11px; color:#f4f7ff; overflow:hidden; white-space:nowrap; text-overflow:ellipsis; border:1px solid rgba(255,255,255,0.18); touch-action:none; }
  .trim-handle { position:absolute; top:0; bottom:0; width:6px; background:rgba(240,246,255,0.45); cursor:ew-resize; }
  .trim-handle.left { left:0; border-radius:6px 0 0 6px; }
  .trim-handle.right { right:0; border-radius:0 6px 6px 0; }
  .clip.selected { outline:2px solid #eaf1ff; box-shadow:0 0 0 2px rgba(83,129,255,0.6); }
  .track-row.active .track-name { color:#f8fcff; background:rgba(77,125,255,0.15); }
  .playhead { position:absolute; top:0; bottom:0; width:2px; background:var(--danger); box-shadow:0 0 8px rgba(255,78,117,0.7); pointer-events:none; }
  .ai-mode { color:var(--text-dim); font-size:12px; margin-bottom:8px; }
  .stack { display:grid; gap:6px; margin:8px 0; }
  .btn { border:1px solid transparent; border-radius:6px; padding:7px 11px; background:var(--accent); color:#f7faff; cursor:pointer; font-size:12px; }
  .btn.subtle { background:#212b3f; border-color:#34405a; }
  .btn.narrow { padding:7px 10px; }
  .btn.icon { min-width:56px; }
  #playhead-slider { width:56%; }
  .timecode { min-width:110px; text-align:right; color:var(--text-dim); font-feature-settings:"tnum"; font-variant-numeric:tabular-nums; }
  pre { background:#0f131b; border:1px solid var(--border); border-radius:8px; padding:8px; font-size:11px; overflow:auto; max-height:230px; white-space:pre-wrap; }
  .inspector { margin:8px 0; padding:8px; border:1px solid var(--border); border-radius:8px; background:#0f131b; font-size:12px; color:var(--text-dim); }
  .drop-zone { border:1.5px dashed #3a4a68; border-radius:7px; padding:10px; text-align:center; font-size:11px; color:var(--text-dim); margin-bottom:8px; transition:border-color 0.15s,background 0.15s; cursor:default; }
  .drop-zone.drag-over { border-color:var(--accent); background:rgba(77,125,255,0.08); color:var(--accent); }
  .asset-actions { display:flex; gap:6px; margin-top:4px; }
  .asset-list { margin:0 0 6px; padding:0; list-style:none; }
  .asset-item { padding:7px 8px; border-radius:6px; border:1px solid var(--border); background:#0f131b; margin-bottom:5px; cursor:pointer; transition:border-color 0.1s; }
  .asset-item:hover { border-color:var(--accent); }
  .asset-item-name { font-size:12px; color:var(--text); white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
  .asset-item-meta { font-size:10px; color:var(--text-dim); margin-top:2px; display:flex; gap:8px; flex-wrap:wrap; }
  .asset-badge { display:inline-block; padding:1px 5px; border-radius:3px; font-size:9px; font-weight:600; text-transform:uppercase; letter-spacing:0.4px; }
  .badge-video { background:rgba(46,120,255,0.25); color:#6fa3ff; }
  .badge-audio { background:rgba(203,147,66,0.25); color:#e5b86a; }
  .badge-image { background:rgba(24,180,135,0.25); color:#4addb5; }
  .proxy-pending { color:#a8b2c7; }
  .proxy-ready { color:#4addb5; }
  .proxy-failed { color:var(--danger); }
  `;
  return style;
}
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd apps/desktop-tauri/ui
npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 3: Run full test suite**

```bash
cd apps/desktop-tauri/ui
npm test
```

Expected: ≥30 tests, all `PASS`.

- [ ] **Step 4: Verify build succeeds**

```bash
cd apps/desktop-tauri/ui
npm run build
```

Expected: `dist/` produced with no errors.

---

## Task 12: Final checks

- [ ] **Step 1: Count studioApp.ts lines**

```bash
wc -l apps/desktop-tauri/ui/src/studioApp.ts
```

Expected: ≤ 280 lines (DOM template + CSS + wiring — the two helper functions add bulk but contain zero logic).

- [ ] **Step 2: Verify no ops file imports from studioApp or renderer**

```bash
grep -r "from.*studioApp\|from.*renderer" apps/desktop-tauri/ui/src/ops/
```

Expected: no output.

- [ ] **Step 3: Verify backendApi.ts is unchanged**

```bash
git diff apps/desktop-tauri/ui/src/backendApi.ts
```

Expected: no output (file unchanged).

- [ ] **Step 4: Run tests one final time**

```bash
cd apps/desktop-tauri/ui
npm test
```

Expected: all tests `PASS`.
