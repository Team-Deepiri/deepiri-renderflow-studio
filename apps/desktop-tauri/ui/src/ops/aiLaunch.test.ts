import { describe, it, expect } from "vitest";
import type { Project, Sequence, Track } from "../backendApi";
import { launchAiProject, type LaunchApi } from "./aiLaunch";

/** Records every backend call the launch makes. */
function fakeApi() {
  const calls = {
    projects: [] as string[],
    sequences: [] as { projectId: string; name: string }[],
    tracks: [] as { sequenceId: string; type: string; name: string }[],
    jobs: [] as { projectId: string; prompt: string; mode: string }[],
  };

  const api: LaunchApi = {
    createProject: async (name): Promise<Project> => {
      calls.projects.push(name);
      return {
        id: "proj-1",
        name,
        fps_num: 24,
        fps_den: 1,
        sample_rate: 48000,
        created_at: "2026-01-01T00:00:00Z",
        updated_at: "2026-01-01T00:00:00Z",
      };
    },
    createSequence: async (projectId, name): Promise<Sequence> => {
      calls.sequences.push({ projectId, name });
      return {
        id: "seq-1",
        project_id: projectId,
        name,
        start_tc: "00:00:00:00",
        duration_ticks: 2400,
        resolution_w: 1920,
        resolution_h: 1080,
      };
    },
    createTrack: async (sequenceId, trackType, laneIndex, name): Promise<Track> => {
      calls.tracks.push({ sequenceId, type: trackType, name });
      return {
        id: "track-1",
        sequence_id: sequenceId,
        track_type: trackType as Track["track_type"],
        lane_index: laneIndex,
        name,
        muted: false,
        locked: false,
        solo: false,
      };
    },
    submitAiJob: async (projectId, prompt, mode = "scene") => {
      calls.jobs.push({ projectId, prompt, mode });
      return { job_id: "job-1", status: "queued" };
    },
  };
  return { api, calls };
}

describe("launchAiProject", () => {
  it("turns a prompt into a project with a job already running", async () => {
    const { api, calls } = fakeApi();

    const launched = await launchAiProject("A neon-lit city street", api);

    expect(calls.jobs).toEqual([
      { projectId: "proj-1", prompt: "A neon-lit city street", mode: "scene" },
    ]);
    expect(launched.project.id).toBe("proj-1");
    expect(launched.sequenceId).toBe("seq-1");
    expect(launched.jobId).toBe("job-1");
  });

  it("gives the generated clip a video track to land on", async () => {
    const { api, calls } = fakeApi();

    await launchAiProject("A misty valley", api);

    expect(calls.sequences).toEqual([
      { projectId: "proj-1", name: "Main Sequence" },
    ]);
    expect(calls.tracks).toHaveLength(1);
    expect(calls.tracks[0].type).toBe("video");
  });

  it("names the project after the prompt so it is findable on the home page", async () => {
    const { api, calls } = fakeApi();

    await launchAiProject("  A cozy coffee shop  ", api);

    expect(calls.projects).toEqual(["A cozy coffee shop"]);
  });

  it("keeps long prompts out of the project name", async () => {
    const { api, calls } = fakeApi();
    const longPrompt = "a ".repeat(80) + "end";

    await launchAiProject(longPrompt, api);

    expect(calls.projects[0].length).toBeLessThanOrEqual(60);
  });

  it("refuses an empty prompt without touching the backend", async () => {
    const { api, calls } = fakeApi();

    await expect(launchAiProject("   ", api)).rejects.toThrow(/prompt/i);
    expect(calls.projects).toEqual([]);
    expect(calls.jobs).toEqual([]);
  });
});
