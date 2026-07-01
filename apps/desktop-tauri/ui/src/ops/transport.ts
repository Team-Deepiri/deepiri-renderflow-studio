import type { StudioState } from "../state";

/**
 * Converts a tick (= frame index in UI layer) to a SMPTE-style timecode string.
 * Format: HH:MM:SS:FF
 *
 * In the UI layer 1 tick === 1 frame (at the configured fps).
 */
export function tickToTimecode(tick: number, fps: number): string {
  const totalFrames = Math.floor(tick);
  const frames = totalFrames % fps;
  const totalSeconds = Math.floor(totalFrames / fps);
  const seconds = totalSeconds % 60;
  const totalMinutes = Math.floor(totalSeconds / 60);
  const minutes = totalMinutes % 60;
  const hours = Math.floor(totalMinutes / 60);

  const pad = (n: number, len = 2) => String(n).padStart(len, "0");
  return `${pad(hours)}:${pad(minutes)}:${pad(seconds)}:${pad(frames)}`;
}

/** Moves the playhead to `tick`, clamped to [0, durationTicks]. */
export function seek(state: StudioState, tick: number): StudioState {
  state.timeline.playheadTick = Math.max(
    0,
    Math.min(tick, state.timeline.durationTicks)
  );
  return state;
}

/** Moves the playhead by one frame in the given direction (1 = forward, -1 = back). */
export function jog(state: StudioState, direction: 1 | -1): StudioState {
  return seek(state, state.timeline.playheadTick + direction);
}

/**
 * Starts playback.
 * `setIntervalFn` is injected so tests can replace the real timer.
 * Returns the interval period in ms (1000 / fps).
 */
export function play(
  state: StudioState,
  onTick: () => void,
  setIntervalFn: (cb: () => void, ms: number) => number = window.setInterval
): StudioState {
  const periodMs = Math.round(1000 / state.timeline.fps);
  state.playTimer = setIntervalFn(onTick, periodMs) as unknown as number;
  state.playing = true;
  return state;
}

/** Pauses playback by clearing the play timer. */
export function pause(
  state: StudioState,
  clearIntervalFn: (id: number | undefined) => void = window.clearInterval
): StudioState {
  clearIntervalFn(state.playTimer);
  state.playTimer = undefined;
  state.playing = false;
  return state;
}

/** Stops playback and seeks to the beginning. */
export function stop(
  state: StudioState,
  clearIntervalFn: (id: number | undefined) => void = window.clearInterval
): StudioState {
  pause(state, clearIntervalFn);
  return seek(state, 0);
}

/**
 * Starts shuttle playback at the given speed multiplier.
 * Replaces any existing play timer.
 */
export function shuttle(
  state: StudioState,
  multiplier: number,
  onTick: () => void,
  setIntervalFn: (cb: () => void, ms: number) => number = window.setInterval,
  clearIntervalFn: (id: number | undefined) => void = window.clearInterval
): StudioState {
  // Stop existing timer if running
  clearIntervalFn(state.playTimer);
  state.playTimer = undefined;
  state.playing = false;

  const periodMs = Math.max(
    16,
    Math.round(1000 / (state.timeline.fps * Math.abs(multiplier)))
  );
  state.playTimer = setIntervalFn(onTick, periodMs) as unknown as number;
  state.playing = true;
  return state;
}
