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
} from "./backendApi";

export function bootstrapStudioApp(): void {
  const app = document.querySelector<HTMLDivElement>("#app");
  if (!app) {
    throw new Error("Missing #app root element");
  }

  type Clip = {
    id: number;
    serverId?: string;
    label: string;
    inTick: number;
    outTick: number;
    color: string;
  };

  type Track = {
    id: number;
    serverId?: string;
    name: string;
    kind: "Video" | "Audio";
    lane_index: number;
    clips: Clip[];
  };

  type TimelineSnapshot = {
    timelineState: { fps: number; durationTicks: number; playheadTick: number; tracks: Track[] };
    timelineUiState: { zoom: number; selectedClipId: number | null; activeTrackId: number | null; markers: number[] };
  };

  const timelineState: { fps: number; durationTicks: number; playheadTick: number; tracks: Track[] } = {
    fps: 24,
    durationTicks: 2400,
    playheadTick: 288,
    tracks: [
      {
        id: 1,
        name: "V1 Main",
        kind: "Video",
        lane_index: 1,
        clips: [
          { id: 101, label: "Intro Plate", inTick: 0, outTick: 480, color: "var(--clip-blue)" },
          { id: 102, label: "Interview A", inTick: 540, outTick: 1500, color: "var(--clip-purple)" },
        ],
      },
      {
        id: 2,
        name: "V2 Overlay",
        kind: "Video",
        lane_index: 0,
        clips: [{ id: 201, label: "Lower Third", inTick: 600, outTick: 1120, color: "var(--clip-green)" }],
      },
      {
        id: 3,
        name: "A1 Dialog",
        kind: "Audio",
        lane_index: 0,
        clips: [{ id: 301, label: "Boom", inTick: 0, outTick: 1480, color: "var(--clip-gold)" }],
      },
    ],
  };

  const timelineUiState: {
    zoom: number;
    selectedClipId: number | null;
    activeTrackId: number | null;
    markers: number[];
  } = {
    zoom: 1,
    selectedClipId: null,
    activeTrackId: null,
    markers: [240, 1020, 1780],
  };

  let activeProjectId: string | null = null;
  let activeSequenceId: string | null = null;
  const PLACEHOLDER_ASSET_ID = "00000000-0000-0000-0000-000000000001";

  app.innerHTML = `
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
          <ul id="asset-list" class="asset-list"></ul>
          <button class="btn narrow" id="btn-probe" type="button">Probe Media via Orchestrator</button>
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
    display: flex;
    align-items: center;
    justify-content: space-between;
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
  .panel, .center {
    border-right: 1px solid var(--border);
    background: rgba(20, 24, 33, 0.93);
  }
  .panel { padding: 12px; }
  .panel-title {
    font-size: 13px;
    text-transform: uppercase;
    letter-spacing: 0.8px;
    color: var(--text-dim);
    margin-bottom: 10px;
  }
  .project-meta { display: grid; gap: 8px; margin-bottom: 12px; }
  .project-meta label { font-size: 12px; color: var(--text-dim); display: grid; gap: 4px; }
  .quick-actions { display: grid; gap: 6px; margin-bottom: 12px; }
  .project-meta input, textarea {
    background: #0f131b;
    border: 1px solid var(--border);
    color: var(--text);
    border-radius: 6px;
    padding: 8px;
  }
  .asset-list { margin: 8px 0 12px; padding-left: 18px; color: var(--text-dim); }
  .asset-list li { margin: 4px 0; }
  .center { display: grid; grid-template-rows: 1fr 290px; }
  .monitor { padding: 12px; border-bottom: 1px solid var(--border); display: grid; grid-template-rows: auto 1fr; }
  .monitor-head, .timeline-head {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 10px;
  }
  .monitor-head h3, .timeline-head h3 { margin: 0; font-size: 14px; }
  .preview {
    margin-top: 10px;
    border: 1px dashed #536180;
    border-radius: 10px;
    display: grid;
    place-items: center;
    background: linear-gradient(145deg, #0d1119, #0a0c12);
  }
  .preview-overlay {
    text-align: center;
    display: grid;
    gap: 10px;
    color: var(--text-dim);
    font-size: 12px;
  }
  .timeline { padding: 12px; background: #111621; }
  .timeline-controls { display: flex; align-items: center; gap: 6px; width: 64%; }
  .timeline-grid {
    margin-top: 10px;
    border: 1px solid var(--border);
    border-radius: 8px;
    overflow: hidden;
    background: #0d1119;
    user-select: none;
  }
  .hint { font-size: 11px; color: var(--text-dim); margin-top: 6px; }
  .track-row {
    display: grid;
    grid-template-columns: 110px 1fr;
    min-height: 46px;
    border-bottom: 1px solid #1f2736;
  }
  .track-name {
    border-right: 1px solid #1f2736;
    padding: 10px 8px;
    font-size: 12px;
    color: var(--text-dim);
  }
  .track-lane { position: relative; }
  .marker {
    position: absolute;
    top: 0;
    bottom: 0;
    width: 1px;
    background: rgba(255, 219, 120, 0.9);
    pointer-events: none;
  }
  .clip {
    position: absolute;
    top: 8px;
    bottom: 8px;
    border-radius: 6px;
    padding: 6px 8px;
    font-size: 11px;
    color: #f4f7ff;
    overflow: hidden;
    white-space: nowrap;
    text-overflow: ellipsis;
    border: 1px solid rgba(255, 255, 255, 0.18);
    touch-action: none;
  }
  .trim-handle {
    position: absolute;
    top: 0;
    bottom: 0;
    width: 6px;
    background: rgba(240, 246, 255, 0.45);
    cursor: ew-resize;
  }
  .trim-handle.left { left: 0; border-radius: 6px 0 0 6px; }
  .trim-handle.right { right: 0; border-radius: 0 6px 6px 0; }
  .clip.selected {
    outline: 2px solid #eaf1ff;
    box-shadow: 0 0 0 2px rgba(83, 129, 255, 0.6);
  }
  .track-row.active .track-name { color: #f8fcff; background: rgba(77, 125, 255, 0.15); }
  .playhead {
    position: absolute;
    top: 0;
    bottom: 0;
    width: 2px;
    background: var(--danger);
    box-shadow: 0 0 8px rgba(255, 78, 117, 0.7);
    pointer-events: none;
  }
  .ai-mode { color: var(--text-dim); font-size: 12px; margin-bottom: 8px; }
  .stack { display: grid; gap: 6px; margin: 8px 0; }
  .btn {
    border: 1px solid transparent;
    border-radius: 6px;
    padding: 7px 11px;
    background: var(--accent);
    color: #f7faff;
    cursor: pointer;
    font-size: 12px;
  }
  .btn.subtle { background: #212b3f; border-color: #34405a; }
  .btn.narrow { padding: 7px 10px; }
  .btn.icon { min-width: 56px; }
  #playhead-slider { width: 56%; }
  .timecode {
    min-width: 110px;
    text-align: right;
    color: var(--text-dim);
    font-feature-settings: "tnum";
    font-variant-numeric: tabular-nums;
  }
  pre {
    background: #0f131b;
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 8px;
    font-size: 11px;
    overflow: auto;
    max-height: 230px;
    white-space: pre-wrap;
  }
  .inspector {
    margin: 8px 0;
    padding: 8px;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: #0f131b;
    font-size: 12px;
    color: var(--text-dim);
  }
`;
  document.head.appendChild(style);

  const out = document.querySelector<HTMLPreElement>("#out")!;
  const workspace = document.querySelector<HTMLDivElement>("#workspace")!;
  const aiPanel = document.querySelector<HTMLDivElement>("#ai-panel")!;
  const timecode = document.querySelector<HTMLSpanElement>("#timecode")!;
  const slider = document.querySelector<HTMLInputElement>("#playhead-slider")!;
  const timelineGrid = document.querySelector<HTMLDivElement>("#timeline-grid")!;
  const assetList = document.querySelector<HTMLUListElement>("#asset-list")!;
  const fpsInput = document.querySelector<HTMLInputElement>("#project-fps")!;
  const aiPrompt = document.querySelector<HTMLTextAreaElement>("#ai-prompt")!;
  const inspector = document.querySelector<HTMLDivElement>("#inspector")!;
  const zoomInput = document.querySelector<HTMLInputElement>("#timeline-zoom")!;

  let aiVisible = true;
  let playing = false;
  let playTimer: number | undefined;
  let lastJobId = "";
  let nextClipId = 1000;
  let suppressHistory = false;

  const historyPast: TimelineSnapshot[] = [];
  const historyFuture: TimelineSnapshot[] = [];
  const PROJECT_STORAGE_KEY = "renderflow.studio.project";

  function tickToTimecode(tick: number, fps: number): string {
    const totalFrames = Math.max(0, Math.floor(tick));
    const hours = Math.floor(totalFrames / (fps * 3600));
    const minutes = Math.floor((totalFrames % (fps * 3600)) / (fps * 60));
    const seconds = Math.floor((totalFrames % (fps * 60)) / fps);
    const frames = totalFrames % fps;
    const p2 = (v: number) => String(v).padStart(2, "0");
    return `${p2(hours)}:${p2(minutes)}:${p2(seconds)}:${p2(frames)}`;
  }

  function getClipById(clipId: number) {
    for (const track of timelineState.tracks) {
      const clip = track.clips.find((c) => c.id === clipId);
      if (clip) return { track, clip };
    }
    return null;
  }

  function serializeSnapshot(): TimelineSnapshot {
    return {
      timelineState: JSON.parse(JSON.stringify(timelineState)) as TimelineSnapshot["timelineState"],
      timelineUiState: JSON.parse(JSON.stringify(timelineUiState)) as TimelineSnapshot["timelineUiState"],
    };
  }

  function applySnapshot(snapshot: TimelineSnapshot) {
    timelineState.fps = snapshot.timelineState.fps;
    timelineState.durationTicks = snapshot.timelineState.durationTicks;
    timelineState.playheadTick = snapshot.timelineState.playheadTick;
    timelineState.tracks = snapshot.timelineState.tracks;

    timelineUiState.zoom = snapshot.timelineUiState.zoom;
    timelineUiState.selectedClipId = snapshot.timelineUiState.selectedClipId;
    timelineUiState.activeTrackId = snapshot.timelineUiState.activeTrackId;
    timelineUiState.markers = snapshot.timelineUiState.markers;

    fpsInput.value = String(timelineState.fps);
    zoomInput.value = String(timelineUiState.zoom);
  }

  function commitHistory(label: string) {
    if (suppressHistory) return;
    historyPast.push(serializeSnapshot());
    if (historyPast.length > 80) historyPast.shift();
    historyFuture.length = 0;
    writeOutput({ history: label, checkpoints: historyPast.length });
  }

  function undoHistory() {
    const prev = historyPast.pop();
    if (!prev) {
      writeOutput("No undo history.");
      return;
    }
    historyFuture.push(serializeSnapshot());
    suppressHistory = true;
    applySnapshot(prev);
    suppressHistory = false;
    renderTimeline();
  }

  function redoHistory() {
    const next = historyFuture.pop();
    if (!next) {
      writeOutput("No redo history.");
      return;
    }
    historyPast.push(serializeSnapshot());
    suppressHistory = true;
    applySnapshot(next);
    suppressHistory = false;
    renderTimeline();
  }

  function saveProjectToStorage() {
    const projectName = (document.querySelector<HTMLInputElement>("#project-name")?.value ?? "Untitled").trim();
    const payload = {
      projectName,
      snapshot: serializeSnapshot(),
      savedAt: new Date().toISOString(),
    };
    window.localStorage.setItem(PROJECT_STORAGE_KEY, JSON.stringify(payload));
    writeOutput({ action: "save_project", projectName, savedAt: payload.savedAt });
  }

  function loadProjectFromStorage() {
    const raw = window.localStorage.getItem(PROJECT_STORAGE_KEY);
    if (!raw) {
      writeOutput("No saved project in localStorage yet.");
      return;
    }
    const parsed = JSON.parse(raw) as { projectName: string; snapshot: TimelineSnapshot; savedAt: string };
    const projectNameInput = document.querySelector<HTMLInputElement>("#project-name");
    if (projectNameInput) projectNameInput.value = parsed.projectName;
    commitHistory("before_load_project");
    suppressHistory = true;
    applySnapshot(parsed.snapshot);
    suppressHistory = false;
    renderTimeline();
    writeOutput({ action: "load_project", projectName: parsed.projectName, savedAt: parsed.savedAt });
  }

  function updateInspector() {
    if (timelineUiState.selectedClipId == null) {
      inspector.textContent = "No clip selected.";
      return;
    }
    const ref = getClipById(timelineUiState.selectedClipId);
    if (!ref) {
      inspector.textContent = "Selected clip is no longer available.";
      return;
    }
    const duration = ref.clip.outTick - ref.clip.inTick;
    inspector.textContent = `${ref.track.name}: ${ref.clip.label} | in ${ref.clip.inTick} | out ${ref.clip.outTick} | len ${duration}f`;
  }

  function clearPlayTimer() {
    if (playTimer) window.clearInterval(playTimer);
    playTimer = undefined;
    playing = false;
    const button = document.querySelector<HTMLButtonElement>("#btn-play");
    if (button) button.textContent = "Play";
  }

  function setPlayhead(next: number) {
    timelineState.playheadTick = Math.max(0, Math.min(timelineState.durationTicks, Math.round(next)));
    renderTimeline();
  }

  function renderTimeline() {
    const duration = timelineState.durationTicks;
    const scaledDuration = duration * timelineUiState.zoom;
    timelineGrid.innerHTML = "";
    for (const track of timelineState.tracks) {
      const row = document.createElement("div");
      row.className = "track-row";
      if (track.id === timelineUiState.activeTrackId) row.classList.add("active");

      const name = document.createElement("div");
      name.className = "track-name";
      name.textContent = `${track.name} (${track.kind})`;
      name.addEventListener("click", () => {
        timelineUiState.activeTrackId = track.id;
        renderTimeline();
      });

      const lane = document.createElement("div");
      lane.className = "track-lane";
      lane.addEventListener("click", (event) => {
        const rect = lane.getBoundingClientRect();
        const ratio = (event.clientX - rect.left) / rect.width;
        setPlayhead((ratio * scaledDuration) / timelineUiState.zoom);
        timelineUiState.activeTrackId = track.id;
      });

      for (const markerTick of timelineUiState.markers) {
        const marker = document.createElement("div");
        marker.className = "marker";
        marker.style.left = `${((markerTick * timelineUiState.zoom) / scaledDuration) * 100}%`;
        lane.appendChild(marker);
      }

      for (const clip of track.clips) {
        const clipNode = document.createElement("div");
        clipNode.className = "clip";
        if (clip.id === timelineUiState.selectedClipId) clipNode.classList.add("selected");
        clipNode.style.left = `${((clip.inTick * timelineUiState.zoom) / scaledDuration) * 100}%`;
        clipNode.style.width = `${(((clip.outTick - clip.inTick) * timelineUiState.zoom) / scaledDuration) * 100}%`;
        clipNode.style.background = clip.color;
        clipNode.textContent = clip.label;
        clipNode.draggable = false;
        clipNode.addEventListener("click", (event) => {
          event.stopPropagation();
          timelineUiState.selectedClipId = clip.id;
          timelineUiState.activeTrackId = track.id;
          updateInspector();
          renderTimeline();
        });

        const leftHandle = document.createElement("div");
        leftHandle.className = "trim-handle left";
        const rightHandle = document.createElement("div");
        rightHandle.className = "trim-handle right";
        clipNode.append(leftHandle, rightHandle);

        const beginPointerEdit = (event: PointerEvent, mode: "move" | "trim-left" | "trim-right") => {
          event.stopPropagation();
          event.preventDefault();
          timelineUiState.selectedClipId = clip.id;
          timelineUiState.activeTrackId = track.id;
          renderTimeline();
          commitHistory(mode);
          const startX = event.clientX;
          const startIn = clip.inTick;
          const startOut = clip.outTick;
          const laneWidth = Math.max(1, lane.getBoundingClientRect().width);
          const ticksPerPx = (scaledDuration / timelineUiState.zoom) / laneWidth;

          const onMove = (moveEvent: PointerEvent) => {
            const deltaTick = Math.round((moveEvent.clientX - startX) * ticksPerPx);
            if (mode === "move") {
              const length = startOut - startIn;
              let nextIn = startIn + deltaTick;
              nextIn = Math.max(0, Math.min(timelineState.durationTicks - length, nextIn));
              clip.inTick = nextIn;
              clip.outTick = nextIn + length;
            } else if (mode === "trim-left") {
              const maxIn = startOut - 2;
              clip.inTick = Math.max(0, Math.min(maxIn, startIn + deltaTick));
            } else {
              const minOut = startIn + 2;
              clip.outTick = Math.max(minOut, Math.min(timelineState.durationTicks, startOut + deltaTick));
            }
            track.clips.sort((a, b) => a.inTick - b.inTick);
            renderTimeline();
          };

          const onUp = () => {
            window.removeEventListener("pointermove", onMove);
            window.removeEventListener("pointerup", onUp);
            updateInspector();
          };

          window.addEventListener("pointermove", onMove);
          window.addEventListener("pointerup", onUp);
        };

        clipNode.addEventListener("pointerdown", (event) => beginPointerEdit(event, "move"));
        leftHandle.addEventListener("pointerdown", (event) => beginPointerEdit(event, "trim-left"));
        rightHandle.addEventListener("pointerdown", (event) => beginPointerEdit(event, "trim-right"));
        lane.appendChild(clipNode);
      }

      const playhead = document.createElement("div");
      playhead.className = "playhead";
      playhead.style.left = `${((timelineState.playheadTick * timelineUiState.zoom) / scaledDuration) * 100}%`;
      lane.appendChild(playhead);

      row.append(name, lane);
      timelineGrid.appendChild(row);
    }
    timecode.textContent = tickToTimecode(timelineState.playheadTick, timelineState.fps);
    slider.value = String(timelineState.playheadTick);
    updateInspector();
  }

  function seedAssets() {
    const assets = [
      "cam_a_take03.mov",
      "broll_city_night.mp4",
      "voiceover_v1.wav",
      "logo_anim_rgba.mov",
      "color_lut_709.cube",
    ];
    assetList.innerHTML = assets.map((item) => `<li>${item}</li>`).join("");
    const rows = assetList.querySelectorAll("li");
    rows.forEach((row) => {
      row.addEventListener("click", () => {
        const track = timelineState.tracks.find((t) => t.id === timelineUiState.activeTrackId) ?? timelineState.tracks[0];
        commitHistory("insert_clip_from_asset");
        const duration = 160;
        const nextClip: Clip = {
          id: nextClipId++,
          label: row.textContent?.trim() ?? "asset",
          inTick: timelineState.playheadTick,
          outTick: Math.min(timelineState.durationTicks, timelineState.playheadTick + duration),
          color: track.kind === "Audio" ? "var(--clip-gold)" : "var(--clip-blue)",
        };
        track.clips.push(nextClip);
        track.clips.sort((a, b) => a.inTick - b.inTick);
        timelineUiState.selectedClipId = nextClip.id;
        timelineUiState.activeTrackId = track.id;
        renderTimeline();
      });
    });
  }

  function writeOutput(value: unknown) {
    out.textContent = typeof value === "string" ? value : JSON.stringify(value, null, 2);
  }

  function splitSelectedClip() {
    if (timelineUiState.selectedClipId == null) return;
    const ref = getClipById(timelineUiState.selectedClipId);
    if (!ref) return;
    const t = timelineState.playheadTick;
    if (t <= ref.clip.inTick + 1 || t >= ref.clip.outTick - 1) {
      writeOutput("Playhead must be inside selected clip to split.");
      return;
    }
    const leftOut = t;
    const rightIn = t;
    commitHistory("split_clip");
    const rightClip: Clip = {
      id: nextClipId++,
      label: `${ref.clip.label} B`,
      inTick: rightIn,
      outTick: ref.clip.outTick,
      color: ref.clip.color,
    };
    ref.clip.outTick = leftOut;
    ref.clip.label = `${ref.clip.label} A`;
    ref.track.clips.push(rightClip);
    ref.track.clips.sort((a, b) => a.inTick - b.inTick);
    timelineUiState.selectedClipId = rightClip.id;
    renderTimeline();
    writeOutput({ action: "split", sourceClipId: ref.clip.id, newClipId: rightClip.id });
  }

  function deleteSelectedClip() {
    if (timelineUiState.selectedClipId == null) return;
    for (const track of timelineState.tracks) {
      const idx = track.clips.findIndex((c) => c.id === timelineUiState.selectedClipId);
      if (idx >= 0) {
        commitHistory("delete_clip");
        const removed = track.clips.splice(idx, 1)[0];
        timelineUiState.selectedClipId = null;
        renderTimeline();
        writeOutput({ action: "delete_clip", clip: removed.label, id: removed.id });
        return;
      }
    }
  }

  function jog(direction: -1 | 1) {
    setPlayhead(timelineState.playheadTick + direction);
  }

  function shuttle(multiplier: number) {
    clearPlayTimer();
    if (multiplier === 0) return;
    playing = true;
    const button = document.querySelector<HTMLButtonElement>("#btn-play");
    if (button) button.textContent = "Pause";
    playTimer = window.setInterval(() => {
      const next = timelineState.playheadTick + multiplier;
      if (next > timelineState.durationTicks) {
        setPlayhead(0);
        return;
      }
      if (next < 0) {
        setPlayhead(timelineState.durationTicks);
        return;
      }
      setPlayhead(next);
    }, Math.max(15, Math.round(1000 / timelineState.fps)));
  }

  document.querySelector("#btn-health")!.addEventListener("click", async () => {
    try {
      const r = await orchestratorHealth();
      writeOutput(r);
    } catch (e) {
      writeOutput(e);
    }
  });

  document.querySelector("#btn-projects")!.addEventListener("click", async () => {
    try {
      const r = await orchestratorListProjects();
      writeOutput(r);
    } catch (e) {
      writeOutput(e);
    }
  });

  document.querySelector("#btn-vulkan")!.addEventListener("click", async () => {
    try {
      const r = await vulkanDiscover();
      writeOutput(r);
    } catch (e) {
      writeOutput(e);
    }
  });

  document.querySelector("#btn-timeline")!.addEventListener("click", async () => {
    try {
      const r = await timelineResolveActive({
        playhead_tick: timelineState.playheadTick,
        sequence: {
          tracks: timelineState.tracks.map((t) => ({
            id: t.id,
            kind: t.kind,
            lane_index: t.lane_index,
            name: t.name,
          })),
          clips: timelineState.tracks.flatMap((t) =>
            t.clips.map((c) => ({
              id: c.id,
              track_id: t.id,
              asset_id: c.id + 9000,
              span: { in_tick: c.inTick, out_tick: c.outTick },
              src_in_tick: 0,
            })),
          ),
        },
      });
      writeOutput(r);
    } catch (e) {
      writeOutput(e);
    }
  });

  document.querySelector("#btn-probe")!.addEventListener("click", async () => {
    const path = window.prompt("Path or URL to probe (ffprobe):", "/tmp/sample.mp4");
    if (!path) return;
    try {
      writeOutput(await probeMedia(path));
    } catch (e) {
      writeOutput(e);
    }
  });

  document.querySelector("#btn-submit-job")!.addEventListener("click", async () => {
    const prompt = aiPrompt.value.trim();
    if (!prompt) {
      writeOutput("Enter an AI prompt first.");
      return;
    }
    try {
      const result = await submitAiJob(prompt);
      lastJobId = result.job_id;
      writeOutput({ submitted: result, hint: "Use Refresh Job to poll status." });
    } catch (e) {
      writeOutput(e);
    }
  });

  document.querySelector("#btn-refresh-job")!.addEventListener("click", async () => {
    if (!lastJobId) {
      writeOutput("No known job id yet. Submit a job first.");
      return;
    }
    try {
      const result = await getAiJob(lastJobId);
      writeOutput(result);
    } catch (e) {
      writeOutput(e);
    }
  });

  document.querySelector("#btn-toggle-ai")!.addEventListener("click", () => {
    aiVisible = !aiVisible;
    aiPanel.style.display = aiVisible ? "block" : "none";
    workspace.classList.toggle("ai-hidden", !aiVisible);
    const button = document.querySelector<HTMLButtonElement>("#btn-toggle-ai")!;
    button.textContent = aiVisible ? "Hide AI Panel" : "Show AI Panel";
  });

  document.querySelector("#btn-toggle-theme")!.addEventListener("click", () => {
    const current = document.body.style.filter;
    document.body.style.filter = current ? "" : "hue-rotate(18deg) saturate(1.05)";
  });

  document.querySelector("#btn-add-marker")!.addEventListener("click", () => {
    timelineUiState.markers.push(timelineState.playheadTick);
    timelineUiState.markers = Array.from(new Set(timelineUiState.markers)).sort((a, b) => a - b);
    renderTimeline();
  });

  document.querySelector("#btn-jump-next-marker")!.addEventListener("click", () => {
    const next = timelineUiState.markers.find((m) => m > timelineState.playheadTick);
    if (next == null) {
      setPlayhead(0);
      return;
    }
    setPlayhead(next);
  });

  document.querySelector("#btn-new-project")!.addEventListener("click", async () => {
    commitHistory("new_project");
    const projectNameInput = document.querySelector<HTMLInputElement>("#project-name");
    const projectName = `Untitled ${new Date().toLocaleTimeString()}`;
    if (projectNameInput) projectNameInput.value = projectName;
    try {
      const project = await orchestratorCreateProject(projectName);
      activeProjectId = project.id;
      const seq = await orchestratorCreateSequence(project.id, "Main Sequence");
      activeSequenceId = seq.id;
      timelineState.tracks = [];
      timelineState.playheadTick = 0;
      timelineUiState.selectedClipId = null;
      timelineUiState.activeTrackId = null;
      timelineUiState.markers = [];
      writeOutput({ action: "new_project", projectId: project.id, sequenceId: seq.id });
    } catch (e) {
      writeOutput({ action: "new_project_error", error: String(e) });
    }
    renderTimeline();
  });

  document.querySelector("#btn-save-project")!.addEventListener("click", async () => {
    if (!activeProjectId || !activeSequenceId) {
      writeOutput("No active server project. Click New Project first.");
      return;
    }
    try {
      for (const track of timelineState.tracks) {
        if (!track.serverId) {
          const t = await orchestratorCreateTrack(activeSequenceId, track.kind.toLowerCase(), track.lane_index, track.name);
          track.serverId = t.id;
        }
        for (const clip of track.clips) {
          if (!clip.serverId && track.serverId) {
            const c = await orchestratorCreateClip(activeSequenceId, track.serverId, PLACEHOLDER_ASSET_ID, clip.inTick, clip.outTick);
            clip.serverId = c.id;
          }
        }
      }
      writeOutput({ action: "save_project", projectId: activeProjectId, tracks: timelineState.tracks.length });
    } catch (e) {
      writeOutput({ action: "save_error", error: String(e) });
    }
  });

  document.querySelector("#btn-load-project")!.addEventListener("click", async () => {
    try {
      const result = await orchestratorListProjects();
      if (!result.items.length) {
        writeOutput("No projects found on orchestrator.");
        return;
      }
      writeOutput({ available_projects: result.items.map((p, i) => `${i + 1}. ${p.name} (${p.id})`) });
      const project = result.items[result.items.length - 1];

      activeProjectId = project.id;
      const sequences = await orchestratorListSequences(project.id) as any[];
      if (!sequences.length) { writeOutput("Project has no sequences."); return; }
      const seq = sequences[0];
      activeSequenceId = seq.id;

      const tracks = await orchestratorListTracks(seq.id);
      const clips = await orchestratorListClips(seq.id);

      let nextId = Date.now();
      timelineState.tracks = tracks.map((t) => ({
        id: nextId++,
        serverId: t.id,
        name: t.name,
        kind: (t.track_type === "audio" ? "Audio" : "Video") as "Video" | "Audio",
        lane_index: t.lane_index,
        clips: clips
          .filter((c: any) => c.track_id === t.id)
          .map((c: any) => ({
            id: nextId++,
            serverId: c.id,
            label: c.name || "Clip",
            inTick: c.in_tick,
            outTick: c.out_tick,
            color: "var(--clip-blue)",
          })),
      }));

      const projectNameInput = document.querySelector<HTMLInputElement>("#project-name");
      if (projectNameInput) projectNameInput.value = project.name;
      renderTimeline();
      writeOutput({ action: "load_project", projectId: project.id, tracks: tracks.length, clips: clips.length });
    } catch (e) {
      writeOutput({ action: "load_error", error: String(e) });
    }
  });

  document.querySelector("#btn-undo")!.addEventListener("click", () => {
    undoHistory();
  });

  document.querySelector("#btn-redo")!.addEventListener("click", () => {
    redoHistory();
  });

  document.querySelector("#btn-back")!.addEventListener("click", () => {
    jog(-1);
  });

  document.querySelector("#btn-forward")!.addEventListener("click", () => {
    jog(1);
  });

  document.querySelector("#btn-play")!.addEventListener("click", () => {
    if (playing) {
      clearPlayTimer();
      return;
    }
    shuttle(1);
  });

  slider.addEventListener("input", () => {
    setPlayhead(Number(slider.value));
  });

  fpsInput.addEventListener("change", () => {
    const next = Number(fpsInput.value);
    if (Number.isFinite(next) && next > 0 && next <= 120) {
      timelineState.fps = Math.floor(next);
      renderTimeline();
    } else {
      fpsInput.value = String(timelineState.fps);
    }
  });

  zoomInput.addEventListener("input", () => {
    commitHistory("zoom_change");
    timelineUiState.zoom = Number(zoomInput.value);
    renderTimeline();
  });

  document.querySelector("#btn-split-clip")!.addEventListener("click", () => {
    splitSelectedClip();
  });

  document.querySelector("#btn-delete-clip")!.addEventListener("click", () => {
    deleteSelectedClip();
  });

  window.addEventListener("keydown", (event) => {
    if ((event.target as HTMLElement)?.tagName === "TEXTAREA" || (event.target as HTMLElement)?.tagName === "INPUT") {
      return;
    }
    if (event.key === "ArrowLeft") {
      event.preventDefault();
      jog(-1);
      return;
    }
    if (event.key === "ArrowRight") {
      event.preventDefault();
      jog(1);
      return;
    }
    if (event.key.toLowerCase() === "j") {
      event.preventDefault();
      shuttle(-2);
      return;
    }
    if (event.key.toLowerCase() === "k") {
      event.preventDefault();
      clearPlayTimer();
      return;
    }
    if (event.key.toLowerCase() === "l") {
      event.preventDefault();
      shuttle(2);
      return;
    }
    if (event.key.toLowerCase() === "m") {
      event.preventDefault();
      commitHistory("add_marker");
      timelineUiState.markers.push(timelineState.playheadTick);
      timelineUiState.markers = Array.from(new Set(timelineUiState.markers)).sort((a, b) => a - b);
      renderTimeline();
      return;
    }
    if (event.key.toLowerCase() === "s") {
      event.preventDefault();
      splitSelectedClip();
      return;
    }
    if (event.key === "Delete" || event.key === "Backspace") {
      event.preventDefault();
      deleteSelectedClip();
      return;
    }
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "z" && !event.shiftKey) {
      event.preventDefault();
      undoHistory();
      return;
    }
    if (
      ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "y") ||
      ((event.ctrlKey || event.metaKey) && event.shiftKey && event.key.toLowerCase() === "z")
    ) {
      event.preventDefault();
      redoHistory();
    }
  });

  seedAssets();
  timelineUiState.activeTrackId = timelineState.tracks[0]?.id ?? null;
  renderTimeline();
}
