import type { Project, Sequence, Track } from "../backendApi";

/** The backend calls launchAiProject needs, injected so it stays testable. */
export type LaunchApi = {
  createProject: (name: string) => Promise<Project>;
  createSequence: (projectId: string, name: string) => Promise<Sequence>;
  createTrack: (
    sequenceId: string,
    trackType: string,
    laneIndex: number,
    name: string,
  ) => Promise<Track>;
  submitAiJob: (
    projectId: string,
    prompt: string,
    mode?: string,
  ) => Promise<{ job_id: string; status: string }>;
};

export type LaunchedProject = {
  project: Project;
  sequenceId: string;
  jobId: string;
};

/** Longest project name we derive from a prompt before trimming it down. */
const NAME_LIMIT = 60;

/** A prompt makes a poor title past a line or so — cut it at a word boundary. */
function projectNameFor(prompt: string): string {
  if (prompt.length <= NAME_LIMIT) return prompt;
  const cut = prompt.slice(0, NAME_LIMIT);
  const lastSpace = cut.lastIndexOf(" ");
  return (lastSpace > 20 ? cut.slice(0, lastSpace) : cut).trimEnd();
}

/**
 * Takes a home-page prompt all the way to a running generation: a project to
 * hold the result, a sequence with a video track for the clip to land on, and
 * a submitted AI job.
 *
 * Throws on an empty prompt so the caller can keep the user on the home page.
 */
export async function launchAiProject(
  prompt: string,
  api: LaunchApi,
  mode = "scene",
): Promise<LaunchedProject> {
  const trimmed = prompt.trim();
  if (!trimmed) throw new Error("Enter a prompt describing the video first.");

  const project = await api.createProject(projectNameFor(trimmed));
  const sequence = await api.createSequence(project.id, "Main Sequence");
  await api.createTrack(sequence.id, "video", 0, "V1");
  const job = await api.submitAiJob(project.id, trimmed, mode);

  return { project, sequenceId: sequence.id, jobId: job.job_id };
}
