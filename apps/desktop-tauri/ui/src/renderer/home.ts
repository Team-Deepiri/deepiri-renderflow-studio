import type { Project } from "../backendApi";
import { orchestratorDeleteProject } from "../backendApi";
import { brandHtml } from "./brand";
import { escapeHtml } from "./escape";

/**
 * Starter prompts offered on the home page, ChatGPT-style. Picking one goes
 * straight to generating — the user never has to think up a first prompt.
 */
export const AI_SUGGESTIONS: string[] = [
  "A neon-lit city street at night, just after rain",
  "Slow drone shot drifting over a misty mountain valley",
  "A cozy coffee shop in warm morning light",
  "Timelapse of a city skyline turning from day to night",
];

/** Markup for the whole home view: topbar, prompt hero, and project grid. */
export function homeViewHtml(): string {
  const chips = AI_SUGGESTIONS.map(
    (s) =>
      `<button class="suggestion-chip" type="button" data-prompt="${escapeHtml(s)}">${escapeHtml(s)}</button>`,
  ).join("");

  return `
<div id="home-view" class="home-view">
  <header class="topbar topbar-home">
    ${brandHtml("brand-home")}
    <div class="toolbar">
      <button class="btn subtle" id="btn-toggle-theme-home" type="button">Theme</button>
    </div>
  </header>
  <main class="home-main">
    <section class="home-hero">
      <h1><span class="word-render">Render</span><span class="word-flow">Flow</span> <span class="hero-studio">Studio</span></h1>
      <p class="hero-sub">Describe the video you want. We generate it and drop it straight onto your timeline.</p>
      <div class="prompt-box">
        <textarea id="home-prompt" rows="3" placeholder="Describe a scene to generate..."></textarea>
        <div class="prompt-actions">
          <button class="btn subtle" id="btn-home-new-project" type="button">Start from a template</button>
          <button class="btn" id="btn-home-generate" type="button">Generate video</button>
        </div>
      </div>
      <div class="suggestions" id="home-suggestions">${chips}</div>
      <div class="prompt-status" id="home-prompt-status"></div>
    </section>
    <section class="home-projects">
      <div class="home-section-header"><h2>Your Projects</h2><span class="home-project-count" id="home-project-count"></span><button class="btn subtle narrow" id="btn-home-refresh" type="button">Refresh</button></div>
      <div id="home-project-list" class="home-project-grid"><div class="home-empty"><p>No projects yet. Describe a scene above to create your first one.</p></div></div>
      <div id="home-loading" class="home-loading" style="display:none"><p>Loading projects...</p></div>
      <div id="home-error" class="home-error" style="display:none"><p>Could not connect to the orchestrator. Make sure the backend is running.</p><button class="btn subtle" id="btn-home-retry" type="button">Retry</button></div>
    </section>
  </main>
</div>`;
}

export type HomeCallbacks = {
  onOpenProject: (project: Project) => void;
  onNewProject: () => void;
  onRefresh: () => void;
  onDeleteProject: (projectId: string) => void;
};

/**
 * Renders the project grid on the home page.
 * Handles loading, empty, and error states.
 */
export async function renderHomeProjects(
  projects: Project[],
  listEl: HTMLElement,
  countEl: HTMLElement,
  loadingEl: HTMLElement,
  errorEl: HTMLElement,
  callbacks: HomeCallbacks,
): Promise<void> {
  listEl.innerHTML = "";
  countEl.textContent = "";
  loadingEl.style.display = "";
  errorEl.style.display = "none";

  try {
    loadingEl.style.display = "none";
    countEl.textContent = `${projects.length} project${projects.length !== 1 ? "s" : ""}`;

    if (!projects.length) {
      listEl.innerHTML = `
        <div class="home-empty">
          <p>No projects yet. Create your first project to get started!</p>
        </div>`;
      return;
    }

    const cards = projects
      .map((p) => {
        const created = new Date(p.created_at).toLocaleDateString(undefined, {
          year: "numeric",
          month: "short",
          day: "numeric",
        });
        const fpsLabel = `${p.fps_num}/${p.fps_den} fps`;
        return `
          <div class="home-project-card" data-project-id="${p.id}">
            <div class="home-project-card-name">${escapeHtml(p.name)}</div>
            <div class="home-project-card-meta">
              <span>&#x1F4C5; ${created}</span>
              <span>&#x1F3AC; ${fpsLabel}</span>
            </div>
            <div class="home-project-card-actions">
              <button class="btn narrow" data-action="open" data-project-id="${p.id}">Open</button>
              <button class="btn narrow subtle" data-action="delete" data-project-id="${p.id}">Delete</button>
            </div>
          </div>`;
      })
      .join("");

    listEl.innerHTML = cards;

    // Wire up card clicks
    listEl
      .querySelectorAll<HTMLDivElement>(".home-project-card")
      .forEach((card) => {
        card.addEventListener("click", async (e) => {
          const target = e.target as HTMLElement;
          if (target.closest("button")) return;
          const projectId = card.dataset.projectId!;
          const project = projects.find((p) => p.id === projectId);
          if (project) callbacks.onOpenProject(project);
        });
      });

    listEl
      .querySelectorAll<HTMLButtonElement>("[data-action='open']")
      .forEach((btn) => {
        btn.addEventListener("click", async (e) => {
          e.stopPropagation();
          const projectId = btn.dataset.projectId!;
          const project = projects.find((p) => p.id === projectId);
          if (project) callbacks.onOpenProject(project);
        });
      });

    listEl
      .querySelectorAll<HTMLButtonElement>("[data-action='delete']")
      .forEach((btn) => {
        btn.addEventListener("click", async (e) => {
          e.stopPropagation();
          const projectId = btn.dataset.projectId!;
          const project = projects.find((p) => p.id === projectId);
          if (!project) return;
          const confirmed = window.confirm(
            `Delete project "${project.name}"? This cannot be undone.`,
          );
          if (!confirmed) return;
          try {
            await orchestratorDeleteProject(projectId);
            callbacks.onDeleteProject(projectId);
          } catch (err) {
            // Say so — a dead-looking button is worse than an error.
            console.error("delete_project_error", err);
            window.alert(`Could not delete "${project.name}": ${String(err)}`);
          }
        });
      });
  } catch {
    loadingEl.style.display = "none";
    errorEl.style.display = "";
  }
}
