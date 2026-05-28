import {
  getAiJob,
  orchestratorHealth,
  orchestratorListProjects,
  orchestratorCreateProject,
  orchestratorCreateSequence,
  orchestratorListSequences,
  orchestratorCreateTrack,
  orchestratorListTracks,
  orchestratorCreateClip,
  orchestratorListClips,
  probeMedia,
  submitAiJob,
  timelineResolveActive,
  vulkanDiscover,
  importMedia,
  listProjectAssets,
  getAsset,
  type Asset,
} from "./backendApi";

import { createInitialState, createHistoryStack } from "./state";
import {
  commitHistory,
  undoHistory,
  redoHistory,
} from "./ops/history";
import { seek, jog, play, pause, shuttle } from "./ops/transport";
import { splitClip, deleteClip, moveClip, trimClip, insertClipFromAsset } from "./ops/clips";
import { addMarker, jumpToNextMarker } from "./ops/markers";
import {
  registerAsset,
  updateAsset,
  startProxyPolling,
  stopProxyPolling,
} from "./ops/assets";
import { saveProject, loadProject } from "./persistence";
import { renderTimeline } from "./renderer/timeline";
import { renderAssetList } from "./renderer/assets";
import { updateInspector } from "./renderer/inspector";
import { registerHotkeys } from "./hotkeys";

const PLACEHOLDER_ASSET_ID = "00000000-0000-0000-0000-000000000001";

export function bootstrapStudioApp(): void {
  const app = document.querySelector<HTMLDivElement>("#app");
  if (!app) throw new Error("Missing #app root element");

  // ── DOM ────────────────────────────────────────────────────────────────────
  app.innerHTML = buildDom();
  document.head.appendChild(buildStyle());

  // ── Element refs ───────────────────────────────────────────────────────────
  const out = document.querySelector<HTMLPreElement>("#out")!;
  const workspace = document.querySelector<HTMLDivElement>("#workspace")!;
  const aiPanel = document.querySelector<HTMLDivElement>("#ai-panel")!;
  const timecodeEl = document.querySelector<HTMLSpanElement>("#timecode")!;
  const slider = document.querySelector<HTMLInputElement>("#playhead-slider")!;
  const timelineGrid = document.querySelector<HTMLDivElement>("#timeline-grid")!;
  const assetListEl = document.querySelector<HTMLUListElement>("#asset-list")!;
  const fpsInput = document.querySelector<HTMLInputElement>("#project-fps")!;
  const aiPrompt = document.querySelector<HTMLTextAreaElement>("#ai-prompt")!;
  const inspectorEl = document.querySelector<HTMLDivElement>("#inspector")!;
  const zoomInput = document.querySelector<HTMLInputElement>("#timeline-zoom")!;

  // ── State ──────────────────────────────────────────────────────────────────
  const state = createInitialState();
  const history = createHistoryStack();

  function writeOutput(value: unknown) {
    out.textContent =
      typeof value === "string" ? value : JSON.stringify(value, null, 2);
  }

  // ── Render helpers ─────────────────────────────────────────────────────────
  function redraw() {
    renderTimeline(state, timelineGrid, timecodeEl, slider, {
      onTrackNameClick(trackId) {
        state.ui.activeTrackId = trackId;
        redraw();
      },
      onLaneClick(trackId, tick) {
        state.ui.activeTrackId = trackId;
        seek(state, tick);
        redraw();
      },
      onClipClick(clipId, trackId) {
        state.ui.selectedClipId = clipId;
        state.ui.activeTrackId = trackId;
        updateInspector(state, inspectorEl);
        redraw();
      },
      onClipPointerDown(clipId, trackId, mode, event, laneRect, scaledDuration) {
        state.ui.selectedClipId = clipId;
        state.ui.activeTrackId = trackId;
        commitHistory(state, history, mode);
        const startX = event.clientX;
        const found = state.timeline.tracks
          .flatMap((t) => t.clips.map((c) => ({ t, c })))
          .find((x) => x.c.id === clipId);
        if (!found) return;
        const startIn = found.c.inTick;
        const startOut = found.c.outTick;
        const laneWidth = Math.max(1, laneRect.width);
        const ticksPerPx =
          (scaledDuration / state.ui.zoom) / laneWidth;

        const onMove = (moveEvent: PointerEvent) => {
          const deltaTick = Math.round(
            (moveEvent.clientX - startX) * ticksPerPx
          );
          if (mode === "move") {
            moveClip(state, clipId, startIn + deltaTick - found.c.inTick, history);
          } else if (mode === "trim-left") {
            const newIn = Math.max(
              0,
              Math.min(startOut - 2, startIn + deltaTick)
            );
            found.c.inTick = newIn;
          } else {
            const newOut = Math.max(
              found.c.inTick + 2,
              Math.min(state.timeline.durationTicks, startOut + deltaTick)
            );
            found.c.outTick = newOut;
          }
          found.t.clips.sort((a, b) => a.inTick - b.inTick);
          redraw();
        };
        const onUp = () => {
          window.removeEventListener("pointermove", onMove);
          window.removeEventListener("pointerup", onUp);
          updateInspector(state, inspectorEl);
        };
        window.addEventListener("pointermove", onMove);
        window.addEventListener("pointerup", onUp);
      },
    });
    updateInspector(state, inspectorEl);
  }

  function redrawAssets() {
    renderAssetList(state.assets, assetListEl, {
      onAssetClick(asset) {
        insertClipFromAsset(state, asset, history);
        redraw();
      },
    });
  }

  // ── Transport buttons ──────────────────────────────────────────────────────
  document.querySelector("#btn-back")!.addEventListener("click", () => {
    jog(state, -1);
    redraw();
  });

  document.querySelector("#btn-forward")!.addEventListener("click", () => {
    jog(state, 1);
    redraw();
  });

  document.querySelector("#btn-play")!.addEventListener("click", () => {
    const btn = document.querySelector<HTMLButtonElement>("#btn-play")!;
    if (state.playing) {
      pause(state, window.clearInterval);
      btn.textContent = "Play";
      redraw();
    } else {
      play(state, () => {
        const next = state.timeline.playheadTick + 1;
        if (next > state.timeline.durationTicks) {
          seek(state, 0);
        } else {
          seek(state, next);
        }
        redraw();
      }, window.setInterval as unknown as (cb: () => void, ms: number) => number);
      btn.textContent = "Pause";
    }
  });

  slider.addEventListener("input", () => {
    seek(state, Number(slider.value));
    redraw();
  });

  fpsInput.addEventListener("change", () => {
    const next = Number(fpsInput.value);
    if (Number.isFinite(next) && next > 0 && next <= 120) {
      state.timeline.fps = Math.floor(next);
      redraw();
    } else {
      fpsInput.value = String(state.timeline.fps);
    }
  });

  zoomInput.addEventListener("input", () => {
    state.ui.zoom = Number(zoomInput.value);
    redraw();
  });

  // ── Edit buttons ───────────────────────────────────────────────────────────
  document.querySelector("#btn-split-clip")!.addEventListener("click", () => {
    splitClip(state, history);
    redraw();
  });

  document.querySelector("#btn-delete-clip")!.addEventListener("click", () => {
    deleteClip(state, history);
    redraw();
  });

  document.querySelector("#btn-undo")!.addEventListener("click", () => {
    undoHistory(state, history);
    fpsInput.value = String(state.timeline.fps);
    zoomInput.value = String(state.ui.zoom);
    redraw();
  });

  document.querySelector("#btn-redo")!.addEventListener("click", () => {
    redoHistory(state, history);
    fpsInput.value = String(state.timeline.fps);
    zoomInput.value = String(state.ui.zoom);
    redraw();
  });

  // ── Marker buttons ─────────────────────────────────────────────────────────
  document.querySelector("#btn-add-marker")!.addEventListener("click", () => {
    addMarker(state, history);
    redraw();
  });

  document.querySelector("#btn-jump-next-marker")!.addEventListener("click", () => {
    jumpToNextMarker(state);
    redraw();
  });

  // ── UI toggle buttons ──────────────────────────────────────────────────────
  document.querySelector("#btn-toggle-ai")!.addEventListener("click", () => {
    state.aiVisible = !state.aiVisible;
    aiPanel.style.display = state.aiVisible ? "block" : "none";
    workspace.classList.toggle("ai-hidden", !state.aiVisible);
    const btn = document.querySelector<HTMLButtonElement>("#btn-toggle-ai")!;
    btn.textContent = state.aiVisible ? "Hide AI Panel" : "Show AI Panel";
  });

  document.querySelector("#btn-toggle-theme")!.addEventListener("click", () => {
    const cur = document.body.style.filter;
    document.body.style.filter = cur ? "" : "hue-rotate(18deg) saturate(1.05)";
  });

  // ── Project persistence ────────────────────────────────────────────────────
  document.querySelector("#btn-save-project")!.addEventListener("click", async () => {
    if (!state.activeProjectId || !state.activeSequenceId) {
      // Save to localStorage when no server project
      const name =
        (document.querySelector<HTMLInputElement>("#project-name")?.value ??
          "Untitled").trim() || "Untitled";
      const snap = {
        timelineState: state.timeline,
        timelineUiState: state.ui,
      };
      saveProject(name, snap);
      writeOutput({ action: "save_project_local", name });
      return;
    }
    try {
      for (const track of state.timeline.tracks) {
        if (!track.serverId) {
          const t = await orchestratorCreateTrack(
            state.activeSequenceId,
            track.kind.toLowerCase(),
            track.lane_index,
            track.name
          );
          track.serverId = t.id;
        }
        for (const clip of track.clips) {
          if (!clip.serverId && track.serverId) {
            const c = await orchestratorCreateClip(
              state.activeSequenceId,
              track.serverId,
              PLACEHOLDER_ASSET_ID,
              clip.inTick,
              clip.outTick
            );
            clip.serverId = c.id;
          }
        }
      }
      writeOutput({
        action: "save_project",
        projectId: state.activeProjectId,
        tracks: state.timeline.tracks.length,
      });
    } catch (e) {
      writeOutput({ action: "save_error", error: String(e) });
    }
  });

  document.querySelector("#btn-load-project")!.addEventListener("click", async () => {
    // Try server load first; fall back to localStorage
    try {
      const result = await orchestratorListProjects();
      if (!result.items.length) {
        // Fall back to localStorage
        const saved = loadProject();
        if (!saved) {
          writeOutput("No saved project found (localStorage or orchestrator).");
          return;
        }
        commitHistory(state, history, "before_load");
        Object.assign(state.timeline, saved.snapshot.timelineState);
        Object.assign(state.ui, saved.snapshot.timelineUiState);
        fpsInput.value = String(state.timeline.fps);
        zoomInput.value = String(state.ui.zoom);
        redraw();
        writeOutput({ action: "load_project_local", name: saved.name });
        return;
      }
      const project = result.items[0];
      state.activeProjectId = project.id;
      const sequences = await orchestratorListSequences(project.id);
      if (!sequences.length) { writeOutput("Project has no sequences."); return; }
      const seq = sequences[0];
      state.activeSequenceId = seq.id;

      const tracks = await orchestratorListTracks(seq.id);
      const clips = await orchestratorListClips(seq.id);

      let nextId = Date.now();
      state.timeline.tracks = tracks.map((t) => ({
        id: nextId++,
        serverId: t.id,
        name: t.name,
        kind: (t.track_type === "audio" ? "Audio" : "Video") as "Video" | "Audio",
        lane_index: t.lane_index,
        clips: clips
          .filter((c) => c.track_id === t.id)
          .map((c) => ({
            id: nextId++,
            serverId: c.id,
            label: c.name || "Clip",
            inTick: c.in_tick,
            outTick: c.out_tick,
            color: "#4d7dff",
          })),
      }));

      state.ui.activeTrackId = state.timeline.tracks[0]?.id ?? null;
      const nameInput = document.querySelector<HTMLInputElement>("#project-name");
      if (nameInput) nameInput.value = project.name;

      try {
        const assets = await listProjectAssets(project.id);
        state.assets = [];
        for (const a of assets) registerAsset(state, a);
        if (state.assets.some((a) => a.meta_jsonb?.proxy_status === "pending")) {
          startProxyPolling(
            state,
            getAsset,
            (updated: Asset) => {
              updateAsset(state, updated.id, updated);
              redrawAssets();
            },
            window.setInterval as unknown as (cb: () => void, ms: number) => number
          );
        }
        redrawAssets();
      } catch {
        /* orchestrator may not have assets yet */
      }
      redraw();
      writeOutput({
        action: "load_project",
        projectId: project.id,
        tracks: tracks.length,
        clips: clips.length,
      });
    } catch (e) {
      writeOutput({ action: "load_error", error: String(e) });
    }
  });

  // ── New project ────────────────────────────────────────────────────────────
  document.querySelector("#btn-new-project")!.addEventListener("click", async () => {
    commitHistory(state, history, "new_project");
    const projectName = `Untitled ${new Date().toLocaleTimeString()}`;
    const nameInput = document.querySelector<HTMLInputElement>("#project-name");
    if (nameInput) nameInput.value = projectName;
    try {
      const project = await orchestratorCreateProject(projectName);
      state.activeProjectId = project.id;
      const seq = await orchestratorCreateSequence(project.id, "Main Sequence");
      state.activeSequenceId = seq.id;
      const v1Server = await orchestratorCreateTrack(seq.id, "video", 0, "V1");
      const a1Server = await orchestratorCreateTrack(seq.id, "audio", 0, "A1");
      const v1Id = state.nextClipId++;
      const a1Id = state.nextClipId++;
      state.timeline.tracks = [
        { id: v1Id, serverId: v1Server.id, name: "V1", kind: "Video", lane_index: 0, clips: [] },
        { id: a1Id, serverId: a1Server.id, name: "A1", kind: "Audio", lane_index: 0, clips: [] },
      ];
      state.timeline.playheadTick = 0;
      state.ui.selectedClipId = null;
      state.ui.activeTrackId = v1Id;
      state.ui.markers = [];
      state.assets = [];
      redrawAssets();
      writeOutput({ action: "new_project", projectId: project.id, sequenceId: seq.id });
    } catch (e) {
      writeOutput({ action: "new_project_error", error: String(e) });
    }
    redraw();
  });

  // ── AI / Orchestrator buttons ──────────────────────────────────────────────
  document.querySelector("#btn-health")!.addEventListener("click", async () => {
    try { writeOutput(await orchestratorHealth()); } catch (e) { writeOutput(e); }
  });

  document.querySelector("#btn-projects")!.addEventListener("click", async () => {
    try { writeOutput(await orchestratorListProjects()); } catch (e) { writeOutput(e); }
  });

  document.querySelector("#btn-vulkan")!.addEventListener("click", async () => {
    try { writeOutput(await vulkanDiscover()); } catch (e) { writeOutput(e); }
  });

  document.querySelector("#btn-timeline")!.addEventListener("click", async () => {
    try {
      const r = await timelineResolveActive({
        playhead_tick: state.timeline.playheadTick,
        sequence: {
          tracks: state.timeline.tracks.map((t) => ({
            id: t.id, kind: t.kind, lane_index: t.lane_index, name: t.name,
          })),
          clips: state.timeline.tracks.flatMap((t) =>
            t.clips.map((c) => ({
              id: c.id, track_id: t.id, asset_id: c.id + 9000,
              span: { in_tick: c.inTick, out_tick: c.outTick },
              src_in_tick: 0,
            }))
          ),
        },
      });
      writeOutput(r);
    } catch (e) { writeOutput(e); }
  });

  document.querySelector("#btn-probe")!.addEventListener("click", async () => {
    const path = window.prompt("Path or URL to probe (ffprobe):", "/tmp/sample.mp4");
    if (!path) return;
    try { writeOutput(await probeMedia(path)); } catch (e) { writeOutput(e); }
  });

  document.querySelector("#btn-submit-job")!.addEventListener("click", async () => {
    const prompt = aiPrompt.value.trim();
    if (!prompt) { writeOutput("Enter an AI prompt first."); return; }
    try {
      const result = await submitAiJob(prompt);
      state.lastJobId = result.job_id;
      writeOutput({ submitted: result, hint: "Use Refresh Job to poll status." });
    } catch (e) { writeOutput(e); }
  });

  document.querySelector("#btn-refresh-job")!.addEventListener("click", async () => {
    if (!state.lastJobId) { writeOutput("No known job id yet. Submit a job first."); return; }
    try { writeOutput(await getAiJob(state.lastJobId)); } catch (e) { writeOutput(e); }
  });

  // ── Media import ───────────────────────────────────────────────────────────
  async function handleImportFile(filePath: string) {
    if (!state.activeProjectId) {
      writeOutput("Create or load a project first, then import media.");
      return;
    }
    writeOutput(`Importing: ${filePath}`);
    try {
      const asset = await importMedia(state.activeProjectId, filePath);
      registerAsset(state, asset);
      redrawAssets();
      writeOutput({ action: "import_asset", id: asset.id, kind: asset.kind, duration_ms: asset.duration_ms });
      if (asset.meta_jsonb?.proxy_status === "pending") {
        startProxyPolling(
          state,
          getAsset,
          (updated: Asset) => { updateAsset(state, updated.id, updated); redrawAssets(); },
          window.setInterval as unknown as (cb: () => void, ms: number) => number
        );
      }
    } catch (e) {
      writeOutput({ action: "import_error", error: String(e) });
    }
  }

  document.querySelector("#btn-import-media")!.addEventListener("click", async () => {
    const path = window.prompt("Absolute path to media file:");
    if (!path?.trim()) return;
    await handleImportFile(path.trim());
  });

  const dropZone = document.querySelector<HTMLDivElement>("#drop-zone")!;
  dropZone.addEventListener("dragover", (e) => { e.preventDefault(); dropZone.classList.add("drag-over"); });
  dropZone.addEventListener("dragleave", () => dropZone.classList.remove("drag-over"));
  dropZone.addEventListener("drop", (e) => {
    e.preventDefault();
    dropZone.classList.remove("drag-over");
    // Browser drag-drop
    const files = e.dataTransfer?.files;
    if (files) {
      for (let i = 0; i < files.length; i++) {
        handleImportFile((files[i] as File & { path?: string }).path ?? files[i].name);
      }
    }
  });

  (async () => {
    try {
      const { getCurrentWebview } = await import("@tauri-apps/api/webview");
      await getCurrentWebview().onDragDropEvent(async (event) => {
        if (event.payload.type === "over") { dropZone.classList.add("drag-over"); return; }
        if (event.payload.type === "leave") { dropZone.classList.remove("drag-over"); return; }
        if (event.payload.type === "drop") {
          dropZone.classList.remove("drag-over");
          for (const path of event.payload.paths) await handleImportFile(path);
        }
      });
    } catch { /* Not in Tauri */ }
  })();

  // ── Hotkeys ────────────────────────────────────────────────────────────────
  registerHotkeys({
    jogBack() { jog(state, -1); redraw(); },
    jogForward() { jog(state, 1); redraw(); },
    shuttleBack() {
      shuttle(
        state, -2,
        () => { seek(state, state.timeline.playheadTick - 2); redraw(); },
        window.setInterval as unknown as (cb: () => void, ms: number) => number,
        window.clearInterval
      );
    },
    shuttleStop() {
      pause(state, window.clearInterval);
      document.querySelector<HTMLButtonElement>("#btn-play")!.textContent = "Play";
    },
    shuttleForward() {
      shuttle(
        state, 2,
        () => { seek(state, state.timeline.playheadTick + 2); redraw(); },
        window.setInterval as unknown as (cb: () => void, ms: number) => number,
        window.clearInterval
      );
    },
    addMarker() { addMarker(state, history); redraw(); },
    splitClip() { splitClip(state, history); redraw(); },
    deleteClip() { deleteClip(state, history); redraw(); },
    undo() {
      undoHistory(state, history);
      fpsInput.value = String(state.timeline.fps);
      zoomInput.value = String(state.ui.zoom);
      redraw();
    },
    redo() {
      redoHistory(state, history);
      fpsInput.value = String(state.timeline.fps);
      zoomInput.value = String(state.ui.zoom);
      redraw();
    },
  });

  // ── Initial render ─────────────────────────────────────────────────────────
  state.ui.activeTrackId = state.timeline.tracks[0]?.id ?? null;
  redrawAssets();
  redraw();
}

// ── DOM template ──────────────────────────────────────────────────────────────

function buildDom(): string {
  return `
  <div class="studio">
    <header class="topbar">
      <div class="brand">Deepiri Renderflow Studio</div>
      <div class="toolbar">
        <button class="btn subtle" id="btn-toggle-ai" type="button">Hide AI Panel</button>
        <button class="btn subtle" id="btn-toggle-theme" type="button">Theme</button>
        <button class="btn subtle" id="btn-undo" type="button">Undo</button>
        <button class="btn subtle" id="btn-redo" type="button">Redo</button>
        <button class="btn subtle" id="btn-load-project" type="button">Load</button>
        <button class="btn" id="btn-new-project" type="button">New Project</button>
        <button class="btn" id="btn-save-project" type="button">Save</button>
      </div>
    </header>

    <div class="workspace" id="workspace">
      <aside class="panel left">
        <div class="panel-title">Project Explorer</div>
        <div class="project-meta">
          <label>Name <input id="project-name" value="Brand Film v01" /></label>
          <label>FPS <input id="project-fps" type="number" min="1" max="120" value="24" /></label>
          <label>Zoom <input id="timeline-zoom" type="range" min="0.8" max="3.4" step="0.1" value="1" /></label>
        </div>
        <div class="quick-actions">
          <button class="btn subtle" id="btn-add-marker" type="button">Add Marker @ Playhead</button>
          <button class="btn subtle" id="btn-jump-next-marker" type="button">Next Marker</button>
        </div>
        <div class="asset-section">
          <h4>Assets</h4>
          <div id="drop-zone" class="drop-zone">Drop media files here</div>
          <ul id="asset-list" class="asset-list"></ul>
          <div class="asset-actions">
            <button class="btn narrow" id="btn-import-media" type="button">Import Media</button>
            <button class="btn narrow subtle" id="btn-probe" type="button">Probe</button>
          </div>
        </div>
      </aside>

      <main class="center">
        <section class="monitor">
          <div class="monitor-head">
            <h3>Program Monitor</h3>
            <div class="transport">
              <button class="btn icon" id="btn-back" type="button">-1f</button>
              <button class="btn icon" id="btn-play" type="button">Play</button>
              <button class="btn icon" id="btn-forward" type="button">+1f</button>
              <span class="timecode" id="timecode">00:00:12:00</span>
            </div>
          </div>
          <div id="preview" class="preview">
            <div class="preview-overlay">
              <span>Vulkan preview surface placeholder</span>
              <button class="btn narrow" id="btn-vulkan" type="button">Query Vulkan Devices</button>
            </div>
          </div>
        </section>

        <section class="timeline">
          <div class="timeline-head">
            <h3>Timeline</h3>
            <div class="timeline-controls">
              <input id="playhead-slider" type="range" min="0" max="2400" value="288" />
              <button class="btn subtle" id="btn-split-clip" type="button">Split</button>
              <button class="btn subtle" id="btn-delete-clip" type="button">Delete</button>
            </div>
          </div>
          <div class="hint">Hotkeys: J/K/L shuttle, Arrow keys frame-step, M marker, S split, Del delete</div>
          <div id="timeline-grid" class="timeline-grid"></div>
        </section>
      </main>

      <aside class="panel right" id="ai-panel">
        <div class="panel-title">AI Copilot</div>
        <div class="ai-mode">Manual path parity: every action has a no-AI equivalent.</div>
        <textarea id="ai-prompt" rows="4" placeholder="Describe a scene, shot list, or generation request..."></textarea>
        <div class="stack">
          <button class="btn" id="btn-health" type="button">Orchestrator Health</button>
          <button class="btn" id="btn-projects" type="button">List Projects</button>
          <button class="btn" id="btn-submit-job" type="button">Submit AI Job</button>
          <button class="btn" id="btn-refresh-job" type="button">Refresh Job</button>
          <button class="btn" id="btn-timeline" type="button">Resolve Active Clips (native)</button>
        </div>
        <div id="inspector" class="inspector">No clip selected.</div>
        <pre id="out"></pre>
      </aside>
    </div>
  </div>
`;
}

// ── CSS ───────────────────────────────────────────────────────────────────────

function buildStyle(): HTMLStyleElement {
  const style = document.createElement("style");
  style.textContent = `
  :root {
    --bg: #111319;
    --bg-soft: #181c24;
    --border: #2a3140;
    --text: #f3f6ff;
    --text-dim: #a8b2c7;
    --accent: #4d7dff;
    --danger: #ff4e75;
    --clip-blue: #2e78ff;
    --clip-purple: #8a54f5;
    --clip-green: #18b487;
    --clip-gold: #cb9342;
  }
  body {
    margin: 0;
    font-family: "Segoe UI", "Inter", system-ui, sans-serif;
    background: radial-gradient(circle at 10% 10%, #202a43 0%, #111319 45%);
    color: var(--text);
  }
  .studio { min-height: 100vh; }
  .topbar {
    border-bottom: 1px solid var(--border);
    display: flex; align-items: center; justify-content: space-between;
    padding: 10px 14px;
    background: rgba(17, 19, 25, 0.85);
    backdrop-filter: blur(6px);
  }
  .brand { font-size: 15px; font-weight: 600; letter-spacing: 0.2px; }
  .toolbar { display: flex; gap: 8px; }
  .workspace {
    display: grid;
    grid-template-columns: 280px 1fr 320px;
    min-height: calc(100vh - 57px);
  }
  .workspace.ai-hidden { grid-template-columns: 280px 1fr; }
  .panel, .center { border-right: 1px solid var(--border); background: rgba(20, 24, 33, 0.93); }
  .panel { padding: 12px; }
  .panel-title { font-size: 13px; text-transform: uppercase; letter-spacing: 0.8px; color: var(--text-dim); margin-bottom: 10px; }
  .project-meta { display: grid; gap: 8px; margin-bottom: 12px; }
  .project-meta label { font-size: 12px; color: var(--text-dim); display: grid; gap: 4px; }
  .quick-actions { display: grid; gap: 6px; margin-bottom: 12px; }
  .project-meta input, textarea {
    background: #0f131b; border: 1px solid var(--border); color: var(--text); border-radius: 6px; padding: 8px;
  }
  .asset-list { margin: 0 0 6px; padding: 0; list-style: none; }
  .asset-list li { margin: 4px 0; }
  .center { display: grid; grid-template-rows: 1fr 290px; }
  .monitor { padding: 12px; border-bottom: 1px solid var(--border); display: grid; grid-template-rows: auto 1fr; }
  .monitor-head, .timeline-head { display: flex; justify-content: space-between; align-items: center; gap: 10px; }
  .monitor-head h3, .timeline-head h3 { margin: 0; font-size: 14px; }
  .preview {
    margin-top: 10px; border: 1px dashed #536180; border-radius: 10px;
    display: grid; place-items: center;
    background: linear-gradient(145deg, #0d1119, #0a0c12);
  }
  .preview-overlay { text-align: center; display: grid; gap: 10px; color: var(--text-dim); font-size: 12px; }
  .timeline { padding: 12px; background: #111621; }
  .timeline-controls { display: flex; align-items: center; gap: 6px; width: 64%; }
  .timeline-grid {
    margin-top: 10px; border: 1px solid var(--border); border-radius: 8px;
    overflow: hidden; background: #0d1119; user-select: none;
  }
  .hint { font-size: 11px; color: var(--text-dim); margin-top: 6px; }
  .track-row {
    display: grid; grid-template-columns: 110px 1fr;
    min-height: 46px; border-bottom: 1px solid #1f2736;
  }
  .track-name { border-right: 1px solid #1f2736; padding: 10px 8px; font-size: 12px; color: var(--text-dim); }
  .track-lane { position: relative; }
  .marker { position: absolute; top: 0; bottom: 0; width: 1px; background: rgba(255, 219, 120, 0.9); pointer-events: none; }
  .clip {
    position: absolute; top: 8px; bottom: 8px; border-radius: 6px;
    padding: 6px 8px; font-size: 11px; color: #f4f7ff;
    overflow: hidden; white-space: nowrap; text-overflow: ellipsis;
    border: 1px solid rgba(255, 255, 255, 0.18); touch-action: none;
  }
  .trim-handle { position: absolute; top: 0; bottom: 0; width: 6px; background: rgba(240, 246, 255, 0.45); cursor: ew-resize; }
  .trim-handle.left { left: 0; border-radius: 6px 0 0 6px; }
  .trim-handle.right { right: 0; border-radius: 0 6px 6px 0; }
  .clip.selected { outline: 2px solid #eaf1ff; box-shadow: 0 0 0 2px rgba(83, 129, 255, 0.6); }
  .track-row.active .track-name { color: #f8fcff; background: rgba(77, 125, 255, 0.15); }
  .playhead { position: absolute; top: 0; bottom: 0; width: 2px; background: var(--danger); box-shadow: 0 0 8px rgba(255, 78, 117, 0.7); pointer-events: none; }
  .ai-mode { color: var(--text-dim); font-size: 12px; margin-bottom: 8px; }
  .stack { display: grid; gap: 6px; margin: 8px 0; }
  .btn { border: 1px solid transparent; border-radius: 6px; padding: 7px 11px; background: var(--accent); color: #f7faff; cursor: pointer; font-size: 12px; }
  .btn.subtle { background: #212b3f; border-color: #34405a; }
  .btn.narrow { padding: 7px 10px; }
  .btn.icon { min-width: 56px; }
  #playhead-slider { width: 56%; }
  .timecode { min-width: 110px; text-align: right; color: var(--text-dim); font-feature-settings: "tnum"; font-variant-numeric: tabular-nums; }
  pre { background: #0f131b; border: 1px solid var(--border); border-radius: 8px; padding: 8px; font-size: 11px; overflow: auto; max-height: 230px; white-space: pre-wrap; }
  .inspector { margin: 8px 0; padding: 8px; border: 1px solid var(--border); border-radius: 8px; background: #0f131b; font-size: 12px; color: var(--text-dim); }
  .drop-zone {
    border: 1.5px dashed #3a4a68; border-radius: 7px; padding: 10px;
    text-align: center; font-size: 11px; color: var(--text-dim); margin-bottom: 8px;
    transition: border-color 0.15s, background 0.15s; cursor: default;
  }
  .drop-zone.drag-over { border-color: var(--accent); background: rgba(77, 125, 255, 0.08); color: var(--accent); }
  .asset-actions { display: flex; gap: 6px; margin-top: 4px; }
  .asset-item {
    padding: 7px 8px; border-radius: 6px; border: 1px solid var(--border);
    background: #0f131b; margin-bottom: 5px; cursor: pointer; transition: border-color 0.1s;
  }
  .asset-item:hover { border-color: var(--accent); }
  .asset-item-name { font-size: 12px; color: var(--text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .asset-item-meta { font-size: 10px; color: var(--text-dim); margin-top: 2px; display: flex; gap: 8px; flex-wrap: wrap; }
  .asset-badge { display: inline-block; padding: 1px 5px; border-radius: 3px; font-size: 9px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.4px; }
  .badge-video { background: rgba(46, 120, 255, 0.25); color: #6fa3ff; }
  .badge-audio { background: rgba(203, 147, 66, 0.25); color: #e5b86a; }
  .badge-image { background: rgba(24, 180, 135, 0.25); color: #4addb5; }
  .proxy-pending { color: #a8b2c7; }
  .proxy-ready { color: #4addb5; }
  .proxy-failed { color: var(--danger); }
`;
  return style;
}
