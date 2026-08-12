import type { RenderJob } from "../backendApi";

/** The backend calls runExport needs, injected so it stays testable. */
export type ExportApi = {
  submitRenderJob: (
    projectId: string,
    sequenceId: string,
    preset: string,
  ) => Promise<RenderJob>;
  getRenderJob: (jobId: string) => Promise<RenderJob>;
};

export type ExportOptions = {
  preset?: string;
  /** Called on every poll so callers can show progress. */
  onProgress?: (job: RenderJob) => void;
  /** Delay between polls; overridden in tests. */
  wait?: (ms: number) => Promise<void>;
  pollIntervalMs?: number;
  /** Upper bound on polls so a wedged render can't spin forever. */
  maxPolls?: number;
};

const DONE = new Set(["completed", "failed"]);

const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

/**
 * Renders the sequence through the orchestrator's render-job pipeline and
 * polls until it settles. Returns the final job — a failed render comes
 * back as `status: "failed"` with `error` set rather than throwing, so the
 * caller shows the reason the same way it shows a path.
 */
export async function runExport(
  projectId: string,
  sequenceId: string,
  api: ExportApi,
  opts: ExportOptions = {},
): Promise<RenderJob> {
  const {
    preset = "h264_1080p",
    onProgress,
    wait = sleep,
    pollIntervalMs = 700,
    // ~7 minutes at the default interval — long enough for a real export,
    // short enough that a stuck job surfaces instead of hanging the UI.
    maxPolls = 600,
  } = opts;

  let job = await api.submitRenderJob(projectId, sequenceId, preset);
  onProgress?.(job);

  for (let polls = 0; polls < maxPolls; polls++) {
    if (DONE.has(job.status)) return job;
    await wait(pollIntervalMs);
    job = await api.getRenderJob(job.id);
    onProgress?.(job);
  }

  if (DONE.has(job.status)) return job;
  throw new Error(`Export timed out after ${maxPolls} polls (last status: ${job.status})`);
}
