import type { TimelineSnapshot } from "./types";

export const PROJECT_STORAGE_KEY = "renderflow.studio.project";

type StoredProject = {
  projectName: string;
  snapshot: TimelineSnapshot;
  savedAt: string;
};

/** Persists the project name and a state snapshot to localStorage. */
export function saveProject(name: string, snapshot: TimelineSnapshot): void {
  const payload: StoredProject = {
    projectName: name,
    snapshot,
    savedAt: new Date().toISOString(),
  };
  localStorage.setItem(PROJECT_STORAGE_KEY, JSON.stringify(payload));
}

/**
 * Loads a previously saved project from localStorage.
 * Returns null if nothing is stored or if the stored data is invalid.
 */
export function loadProject(): { name: string; snapshot: TimelineSnapshot } | null {
  const raw = localStorage.getItem(PROJECT_STORAGE_KEY);
  if (!raw) return null;
  try {
    const parsed: StoredProject = JSON.parse(raw);
    return { name: parsed.projectName, snapshot: parsed.snapshot };
  } catch {
    return null;
  }
}
