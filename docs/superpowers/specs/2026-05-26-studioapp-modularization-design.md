# Design: studioApp.ts Modularization

**Date:** 2026-05-26  
**Status:** Approved  
**Branch:** peytonli/refactor/studioApp

---

## Problem

`apps/desktop-tauri/ui/src/studioApp.ts` is a 1,259-line monolith. All state, DOM logic, event handlers, API calls, playback timers, undo/redo, and inline CSS live in a single closure. Adding any new feature requires reading and modifying the entire file.

## Goal

Split `studioApp.ts` into focused modules with clear layer boundaries. Every operation on state must be unit-testable without a DOM or Tauri runtime. `backendApi.ts` stays byte-for-byte identical.

---

## Architecture: Layered (Option C)

```
apps/desktop-tauri/ui/src/
  types.ts                    ← shared TypeScript types (extracted from studioApp.ts)
  state.ts                    ← StudioState + HistoryStack + createInitialState()
  persistence.ts              ← localStorage save/load
  ops/
    clips.ts                  ← splitClip, deleteClip, moveClip, trimClip, insertClipFromAsset
    transport.ts              ← seek, play, pause, stop, jog, shuttle, tickToTimecode
    markers.ts                ← addMarker, jumpToNextMarker, removeMarker
    assets.ts                 ← registerAsset, updateAsset, startProxyPolling, stopProxyPolling
    history.ts                ← commitHistory, undoHistory, redoHistory, snapshotState, applySnapshot
  renderer/
    timeline.ts               ← renderTimeline(state, root, callbacks)
    assets.ts                 ← renderAssetList(assets, root, callbacks)
    inspector.ts              ← updateInspector(state, el)
  hotkeys.ts                  ← registerHotkeys(dispatch) → cleanup fn
  studioApp.ts                ← thin bootstrap: DOM build, element queries, event wiring
  backendApi.ts               ← UNCHANGED
```

### Layer invariants

- **Operations** never import from `renderer/`, `hotkeys.ts`, or `studioApp.ts`
- **Renderers** never mutate state — read-only consumers only
- **`studioApp.ts`** imports everything but adds zero logic
- **`backendApi.ts`** is not modified

---

## Types (`types.ts`)

Extracts all local type definitions from `studioApp.ts`:

```ts
export type Clip = {
  id: number; serverId?: string; label: string;
  inTick: number; outTick: number; color: string;
};

export type Track = {
  id: number; serverId?: string; name: string;
  kind: "Video" | "Audio"; lane_index: number; clips: Clip[];
};

export type TimelineState = {
  fps: number; durationTicks: number; playheadTick: number; tracks: Track[];
};

export type TimelineUiState = {
  zoom: number; selectedClipId: number | null;
  activeTrackId: number | null; markers: number[];
};

export type TimelineSnapshot = { timelineState: TimelineState; timelineUiState: TimelineUiState };

export type { Asset } from "./backendApi";
```

No logic. No tests needed.

---

## State (`state.ts`)

Single mutable object for the entire app:

```ts
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

export function createInitialState(): StudioState
export function createHistoryStack(): HistoryStack
```

---

## Operations (`ops/`)

All pure functions — take state, mutate in-place, return state. Timer-related functions accept injected `setInterval`/`clearInterval` for testability.

### `ops/clips.ts`
```ts
splitClip(state, history): StudioState
deleteClip(state, history): StudioState
moveClip(state, clipId, deltaInTick, history): StudioState
trimClip(state, clipId, side, deltaInTick): StudioState
getClipById(state, clipId): { track, clip } | null
insertClipFromAsset(state, asset, history): StudioState
```

### `ops/transport.ts`
```ts
seek(state, tick): StudioState
play(state, onTick): StudioState
pause(state, clearTimer): StudioState
stop(state, clearTimer): StudioState
jog(state, direction): StudioState
shuttle(state, multiplier, onTick, clearTimer): StudioState
tickToTimecode(tick, fps): string
```

### `ops/markers.ts`
```ts
addMarker(state, history): StudioState
jumpToNextMarker(state): StudioState
removeMarker(state, tick): StudioState
```

### `ops/assets.ts`
```ts
registerAsset(state, asset): StudioState
updateAsset(state, assetId, updated): StudioState
startProxyPolling(state, fetchAsset, onUpdate, setInterval): StudioState
stopProxyPolling(state, clearInterval): StudioState
```

### `ops/history.ts`
```ts
commitHistory(state, history, label): void
undoHistory(state, history): StudioState
redoHistory(state, history): StudioState
snapshotState(state): TimelineSnapshot
applySnapshot(state, snapshot): StudioState
```

---

## Renderers (`renderer/`)

DOM-only, no logic. Receive state + root element + callbacks:

```ts
// renderer/timeline.ts
renderTimeline(state: StudioState, root: HTMLElement, callbacks: TimelineCallbacks): void

// renderer/assets.ts
renderAssetList(assets: Asset[], root: HTMLElement, callbacks: AssetCallbacks): void

// renderer/inspector.ts
updateInspector(state: StudioState, el: HTMLElement): void
```

Not unit-tested — covered by Tauri smoke test.

---

## Bootstrap (`hotkeys.ts` + `studioApp.ts`)

```ts
// hotkeys.ts
registerHotkeys(dispatch: HotkeyDispatch): () => void  // returns cleanup fn

// studioApp.ts — target: <150 lines
bootstrapStudioApp(): void
// builds DOM + <style>, queries elements, creates state + history,
// wires all button/input/keyboard handlers by calling ops then renderers
```

---

## Testing Strategy

| File | Framework | Coverage |
|------|-----------|----------|
| `ops/clips.test.ts` | Vitest | split at boundary, delete missing, move clamp, trim min, insert no track |
| `ops/transport.test.ts` | Vitest | seek clamp, jog at 0, timecode format, shuttle timer replace |
| `ops/markers.test.ts` | Vitest | dedup, sort, wrap-around jump |
| `ops/assets.test.ts` | Vitest | register, update, poll start/stop, no double-poll |
| `ops/history.test.ts` | Vitest | undo/redo no-op, cap 80, deep copy |
| `persistence.test.ts` | Vitest + `vi.stubGlobal` | save/load round-trip, missing key returns null |
| Renderers + Tauri | Smoke test | visual correctness + IPC paths |

Test files: `src/**/*.test.ts` (Vitest default, co-located with source).

### TDD workflow per module
1. Write `*.test.ts` with all cases — red
2. Write stub that compiles — still red on assertions
3. Implement until green
4. Next module

---

## Migration approach

Incremental — `studioApp.ts` keeps working throughout:

1. Install Vitest, write `vitest.config.ts`
2. Extract `types.ts` (no behavior change)
3. Extract `state.ts` + `createInitialState()` — replace scattered `let` vars
4. Implement `ops/history.ts` with tests (lowest deps)
5. Implement `ops/transport.ts` with tests
6. Implement `ops/clips.ts` with tests
7. Implement `ops/markers.ts` with tests
8. Implement `ops/assets.ts` with tests
9. Extract `persistence.ts` with tests
10. Extract `renderer/timeline.ts`, `renderer/assets.ts`, `renderer/inspector.ts`
11. Extract `hotkeys.ts`
12. Slim `studioApp.ts` down to bootstrap wiring
13. Run full build + smoke test

---

## Success criteria

- `npm test` (Vitest) passes with ≥30 unit tests, all green
- `npm run build` produces identical output (no TS errors)
- App launches in Tauri and smoke test passes
- `studioApp.ts` is under 150 lines
- No file in `ops/` or `renderer/` imports from `studioApp.ts`
