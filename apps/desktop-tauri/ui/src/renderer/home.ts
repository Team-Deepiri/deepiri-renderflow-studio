import type { Project } from "../backendApi";
import { orchestratorDeleteProject } from "../backendApi";

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
            <div class="home-project-card-name">${p.name}</div>
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
            console.error("delete_project_error", err);
          }
        });
      });
  } catch {
    loadingEl.style.display = "none";
    errorEl.style.display = "";
  }
}
