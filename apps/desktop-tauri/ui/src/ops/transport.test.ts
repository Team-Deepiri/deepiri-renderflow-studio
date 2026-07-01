import { describe, it, expect, vi, beforeEach } from "vitest";
import { createInitialState } from "../state";
import type { StudioState } from "../state";
import {
  tickToTimecode,
  seek,
  jog,
  play,
  pause,
  stop,
  shuttle,
} from "./transport";

let state: StudioState;

beforeEach(() => {
  state = createInitialState();
  // state.timeline.fps = 24, durationTicks = 2400, playheadTick = 288
});

describe("tickToTimecode", () => {
  it("converts 0 to 00:00:00:00", () => {
    expect(tickToTimecode(0, 24)).toBe("00:00:00:00");
  });

  it("converts 288 ticks at 24fps to 00:00:12:00", () => {
    // 288 frames / 24fps = 12 seconds, 0 frames
    expect(tickToTimecode(288, 24)).toBe("00:00:12:00");
  });

  it("converts 25 ticks at 25fps to 00:00:01:00", () => {
    expect(tickToTimecode(25, 25)).toBe("00:00:01:00");
  });

  it("handles frame sub-second portion", () => {
    // 25 ticks at 24fps: 1 second, 1 frame
    expect(tickToTimecode(25, 24)).toBe("00:00:01:01");
  });

  it("handles hours correctly", () => {
    // 24fps * 60s * 60min * 1hr = 86400 ticks
    expect(tickToTimecode(86400, 24)).toBe("01:00:00:00");
  });

  it("formats sub-components with leading zeros", () => {
    // 24fps * 65s = 1560 ticks → 00:01:05:00
    expect(tickToTimecode(24 * 65, 24)).toBe("00:01:05:00");
  });
});

describe("seek", () => {
  it("sets playheadTick to given tick", () => {
    const result = seek(state, 500);
    expect(result.timeline.playheadTick).toBe(500);
  });

  it("clamps below 0 to 0", () => {
    const result = seek(state, -10);
    expect(result.timeline.playheadTick).toBe(0);
  });

  it("clamps above durationTicks to durationTicks", () => {
    const result = seek(state, 9999);
    expect(result.timeline.playheadTick).toBe(2400);
  });

  it("allows seek to exactly 0", () => {
    const result = seek(state, 0);
    expect(result.timeline.playheadTick).toBe(0);
  });

  it("allows seek to exactly durationTicks", () => {
    const result = seek(state, 2400);
    expect(result.timeline.playheadTick).toBe(2400);
  });
});

describe("jog", () => {
  it("jog(1) moves playhead forward by 1", () => {
    state.timeline.playheadTick = 100;
    const result = jog(state, 1);
    expect(result.timeline.playheadTick).toBe(101);
  });

  it("jog(-1) moves playhead back by 1", () => {
    state.timeline.playheadTick = 100;
    const result = jog(state, -1);
    expect(result.timeline.playheadTick).toBe(99);
  });

  it("does not go below 0", () => {
    state.timeline.playheadTick = 0;
    const result = jog(state, -1);
    expect(result.timeline.playheadTick).toBe(0);
  });

  it("does not exceed durationTicks", () => {
    state.timeline.playheadTick = 2400;
    const result = jog(state, 1);
    expect(result.timeline.playheadTick).toBe(2400);
  });
});

describe("play", () => {
  it("sets playing to true", () => {
    const onTick = vi.fn();
    const fakeSetInterval = vi.fn().mockReturnValue(42);
    const result = play(state, onTick, fakeSetInterval);
    expect(result.playing).toBe(true);
  });

  it("stores the timer ID in playTimer", () => {
    const onTick = vi.fn();
    const fakeSetInterval = vi.fn().mockReturnValue(42);
    const result = play(state, onTick, fakeSetInterval);
    expect(result.playTimer).toBe(42);
  });

  it("calls setInterval with onTick callback", () => {
    const onTick = vi.fn();
    const fakeSetInterval = vi.fn().mockReturnValue(1);
    play(state, onTick, fakeSetInterval);
    expect(fakeSetInterval).toHaveBeenCalledWith(onTick, expect.any(Number));
  });
});

describe("pause", () => {
  it("sets playing to false", () => {
    state.playing = true;
    state.playTimer = 42;
    const fakeClearInterval = vi.fn();
    const result = pause(state, fakeClearInterval);
    expect(result.playing).toBe(false);
  });

  it("calls clearInterval with the stored timer", () => {
    state.playTimer = 42;
    const fakeClearInterval = vi.fn();
    pause(state, fakeClearInterval);
    expect(fakeClearInterval).toHaveBeenCalledWith(42);
  });

  it("sets playTimer to undefined", () => {
    state.playTimer = 42;
    const fakeClearInterval = vi.fn();
    const result = pause(state, fakeClearInterval);
    expect(result.playTimer).toBeUndefined();
  });
});

describe("stop", () => {
  it("pauses and seeks to 0", () => {
    state.playing = true;
    state.playTimer = 42;
    state.timeline.playheadTick = 500;
    const fakeClearInterval = vi.fn();
    const result = stop(state, fakeClearInterval);
    expect(result.playing).toBe(false);
    expect(result.timeline.playheadTick).toBe(0);
  });
});

describe("shuttle", () => {
  it("replaces any existing timer", () => {
    state.playTimer = 10;
    const onTick = vi.fn();
    const fakeClearInterval = vi.fn();
    const fakeSetInterval = vi.fn().mockReturnValue(99);
    shuttle(state, 2, onTick, fakeSetInterval, fakeClearInterval);
    expect(fakeClearInterval).toHaveBeenCalledWith(10);
    expect(fakeSetInterval).toHaveBeenCalled();
  });

  it("sets playing to true", () => {
    const onTick = vi.fn();
    const fakeClearInterval = vi.fn();
    const fakeSetInterval = vi.fn().mockReturnValue(1);
    const result = shuttle(state, 2, onTick, fakeSetInterval, fakeClearInterval);
    expect(result.playing).toBe(true);
  });
});
