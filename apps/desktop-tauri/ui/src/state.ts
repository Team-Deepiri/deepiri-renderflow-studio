import type { Asset } from "./backendApi";
import type { TimelineState, TimelineUiState, TimelineSnapshot } from "./types";

/** The complete application state — one mutable object. */
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
  devMode: boolean;
  currentView: "home" | "studio";
};

/** Undo/redo stack — kept separate from StudioState for clarity. */
export type HistoryStack = {
  past: TimelineSnapshot[];
  future: TimelineSnapshot[];
  suppressHistory: boolean;
};

/** Returns a fresh StudioState with a default 3-track, 2-clip timeline. */
export function createInitialState(): StudioState {
  return {
    timeline: {
      fps: 24,
      durationTicks: 2400,
      playheadTick: 288,
      tracks: [
        {
          id: 1,
          name: "V1 Main",
          kind: "Video",
          lane_index: 0,
          clips: [
            { id: 101, label: "Clip A", inTick: 0, outTick: 480, color: "#4d7dff" },
            { id: 102, label: "Clip B", inTick: 480, outTick: 960, color: "#18b487" },
          ],
        },
        {
          id: 2,
          name: "V2 Overlay",
          kind: "Video",
          lane_index: 1,
          clips: [
            { id: 201, label: "Title", inTick: 240, outTick: 720, color: "#ff8c42" },
          ],
        },
        {
          id: 3,
          name: "A1 Dialog",
          kind: "Audio",
          lane_index: 2,
          clips: [
            { id: 301, label: "VO", inTick: 0, outTick: 960, color: "#a855f7" },
          ],
        },
      ],
    },
    ui: {
      zoom: 1,
      selectedClipId: null,
      activeTrackId: null,
      markers: [],
    },
    activeProjectId: null,
    activeSequenceId: null,
    nextClipId: 400,
    assets: [],
    proxyPollTimer: undefined,
    playing: false,
    playTimer: undefined,
    lastJobId: "",
    aiVisible: false,
    devMode: typeof localStorage !== "undefined" && localStorage.getItem("deepiri_dev_mode") === "true",
    currentView: "home",
  };
}

/** Returns an empty history stack. */
export function createHistoryStack(): HistoryStack {
  return {
    past: [],
    future: [],
    suppressHistory: false,
  };
}
