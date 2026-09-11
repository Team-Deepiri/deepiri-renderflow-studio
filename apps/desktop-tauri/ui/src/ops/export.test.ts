import { describe, it, expect } from "vitest";
import type { RenderJob } from "../backendApi";
import { runExport, saveThenExport, type ExportApi } from "./export";

/** Serves a scripted sequence of render-job states, one per poll. */
function fakeApi(states: Partial<RenderJob>[]) {
  const submitted: { projectId: string; sequenceId: string; preset: string }[] = [];
  let polls = 0;

  const at = (i: number): RenderJob => ({
    id: "render-1",
    project_id: "proj-1",
    sequence_id: "seq-1",
    preset: "h264_1080p",
    status: "queued",
    progress: 0,
    ...states[Math.min(i, states.length - 1)],
  });

  const api: ExportApi = {
    submitRenderJob: async (projectId, sequenceId, preset) => {
      submitted.push({ projectId, sequenceId, preset });
      return at(0);
    },
    getRenderJob: async () => at(++polls),
  };
  return { api, submitted, pollCount: () => polls };
}

const noWait = async () => {};

describe("runExport", () => {
  it("submits the active sequence and returns the finished render", async () => {
    const { api, submitted } = fakeApi([
      { status: "queued" },
      { status: "rendering", progress: 0.5 },
      { status: "completed", progress: 1, output_uri: "C:/data/render_outputs/render-1/export.mp4" },
    ]);

    const job = await runExport("proj-1", "seq-1", api, { wait: noWait });

    expect(submitted).toEqual([{ projectId: "proj-1", sequenceId: "seq-1", preset: "h264_1080p" }]);
    expect(job.status).toBe("completed");
    expect(job.output_uri).toBe("C:/data/render_outputs/render-1/export.mp4");
  });

  it("reports progress on every poll", async () => {
    const { api } = fakeApi([
      { status: "queued" },
      { status: "rendering", progress: 0.1 },
      { status: "rendering", progress: 0.5 },
      { status: "completed", progress: 1 },
    ]);
    const seen: number[] = [];

    await runExport("proj-1", "seq-1", api, { wait: noWait, onProgress: (j) => seen.push(j.progress) });

    expect(seen).toEqual([0, 0.1, 0.5, 1]);
  });

  it("returns the failed render with its reason instead of throwing", async () => {
    const { api } = fakeApi([
      { status: "queued" },
      { status: "failed", error: "no readable clip sources" },
    ]);

    const job = await runExport("proj-1", "seq-1", api, { wait: noWait });

    expect(job.status).toBe("failed");
    expect(job.error).toBe("no readable clip sources");
  });

  it("gives up instead of polling forever when the render never settles", async () => {
    const { api, pollCount } = fakeApi([{ status: "rendering", progress: 0.3 }]);

    await expect(
      runExport("proj-1", "seq-1", api, { wait: noWait, maxPolls: 5 }),
    ).rejects.toThrow(/timed out/i);
    expect(pollCount()).toBe(5);
  });
});

// ── saveThenExport ───────────────────────────────────────────────────────────

const aJob = (over: Partial<RenderJob> = {}): RenderJob => ({
  id: "render-1",
  project_id: "proj-1",
  sequence_id: "seq-1",
  preset: "h264_1080p",
  status: "completed",
  progress: 1,
  ...over,
});

describe("saveThenExport", () => {
  it("saves the timeline before rendering it", async () => {
    const order: string[] = [];

    await saveThenExport(
      async () => {
        order.push("save");
        return null;
      },
      async () => {
        order.push("render");
        return aJob();
      },
    );

    expect(order).toEqual(["save", "render"]);
  });

  it("does not render when the save failed", async () => {
    let rendered = false;

    const result = await saveThenExport(
      async () => "orchestrator unreachable",
      async () => {
        rendered = true;
        return aJob();
      },
    );

    // The whole point: a stale render is worse than no render, because the
    // file looks authoritative while missing every unsaved edit.
    expect(rendered).toBe(false);
    expect(result).toEqual({ ok: false, saveError: "orchestrator unreachable" });
  });

  it("hands the finished render back when the save went through", async () => {
    const job = aJob({ output_uri: "C:/data/render_outputs/render-1/export.mp4" });

    const result = await saveThenExport(async () => null, async () => job);

    expect(result).toEqual({ ok: true, job });
  });

  it("reports a failed render as a render result, not a save failure", async () => {
    const failed = aJob({ status: "failed", error: "no readable clip sources" });

    const result = await saveThenExport(async () => null, async () => failed);

    // runExport resolves on a failed render rather than throwing, so the save
    // gate has to stay out of the way and let the caller read job.status.
    expect(result).toEqual({ ok: true, job: failed });
  });
});
