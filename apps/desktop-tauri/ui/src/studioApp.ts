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
  acceptAiJob,
  submitRenderJob,
  getRenderJob,
  timelineResolveActive,
  vulkanDiscover,
  importMedia,
  listProjectAssets,
  getAsset,
  fetchFrame,
  getStreamUrl,
  type Asset,
} from "./backendApi";

export function bootstrapStudioApp(): void {
  const app = document.querySelector<HTMLDivElement>("#app");
  if (!app) {
    throw new Error("Missing #app root element");
  }

  type Clip = {
    id: number;
    serverId?: string;
    assetId?: string;
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

  type ActiveClipRef = {
    track: Track;
    clip: Clip;
    asset?: Asset;
    trackIndex: number;
  };

  type TimelineSnapshot = {
    timelineState: { fps: number; durationTicks: number; playheadTick: number; tracks: Track[] };
    timelineUiState: { zoom: number; selectedClipId: number | null; activeTrackId: number | null; activeClipIds: number[]; markers: number[] };
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
    activeClipIds: number[];
  } = {
    zoom: 1,
    selectedClipId: null,
    activeTrackId: null,
    markers: [240, 1020, 1780],
    activeClipIds: [],
  };

  let activeProjectId: string | null = null;
  let activeSequenceId: string | null = null;
  let registeredAssets: Asset[] = [];
  let proxyPollTimer: number | undefined;

  function findRegisteredAsset(assetId: string | undefined): Asset | undefined {
    if (!assetId) return undefined;
    const key = String(assetId);
    return registeredAssets.find((a) => String(a.id) === key);
  }

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
        <button class="btn" id="btn-export" type="button">Export</button>
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
            <img id="preview-frame" class="preview-frame" style="display:none" alt="" />
            <video id="preview-video" class="preview-frame" style="display:none" preload="auto"></video>
            <div id="preview-empty" class="preview-overlay">
              <span>No clip at playhead</span>
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
          <button class="btn" id="btn-accept-job" type="button" disabled>Accept Result</button>
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
    position: relative;
    overflow: hidden;
    background: #0d1119;
  }
  .preview-stage {
    position: absolute;
    inset: 0;
  }
  .preview-overlay {
    position: absolute;
    inset: 0;
    text-align: center;
    display: grid;
    place-items: center;
    align-content: center;
    gap: 10px;
    color: var(--text-dim);
    font-size: 12px;
    padding: 16px;
    background: rgba(13, 17, 25, 0.82);
    pointer-events: none;
  }
  .preview-overlay .btn { pointer-events: auto; }
  .preview-layer {
    position: absolute;
    inset: 0;
    overflow: hidden;
  }
  .preview-layer img {
    width: 100%;
    height: 100%;
    object-fit: contain;
    display: block;
  }
  .preview-layer-list {
    position: absolute;
    left: 12px;
    top: 12px;
    display: grid;
    gap: 8px;
    z-index: 20;
    pointer-events: none;
  }
  .preview-layer-item {
    padding: 9px 12px;
    border-radius: 8px;
    background: rgba(13, 17, 25, 0.86);
    color: #f3f6ff;
    font-size: 13px;
    line-height: 1.25;
    border: 1px solid rgba(255, 255, 255, 0.12);
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
  .clip.active-clip {
    box-shadow: 0 0 0 2px rgba(255, 78, 117, 0.85);
    filter: brightness(1.18);
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
    white-space: pre-line;
  }
  .drop-zone {
    border: 1.5px dashed #3a4a68;
    border-radius: 7px;
    padding: 10px;
    text-align: center;
    font-size: 11px;
    color: var(--text-dim);
    margin-bottom: 8px;
    transition: border-color 0.15s, background 0.15s;
    cursor: default;
  }
  .drop-zone.drag-over {
    border-color: var(--accent);
    background: rgba(77, 125, 255, 0.08);
    color: var(--accent);
  }
  .asset-actions { display: flex; gap: 6px; margin-top: 4px; }
  .asset-list { margin: 0 0 6px; padding: 0; list-style: none; }
  .asset-item {
    padding: 7px 8px;
    border-radius: 6px;
    border: 1px solid var(--border);
    background: #0f131b;
    margin-bottom: 5px;
    cursor: pointer;
    transition: border-color 0.1s;
  }
  .asset-item:hover { border-color: var(--accent); }
  .asset-item { position: relative; }
  .asset-remove {
    position: absolute;
    top: 6px;
    right: 6px;
    background: none;
    border: none;
    color: var(--text-dim);
    font-size: 13px;
    cursor: pointer;
    line-height: 1;
    padding: 0 2px;
    opacity: 0;
    transition: opacity 0.1s, color 0.1s;
  }
  .asset-item:hover .asset-remove { opacity: 1; }
  .asset-remove:hover { color: var(--danger); }
  .asset-add-timeline {
    position: absolute;
    top: 6px;
    right: 28px;
    background: none;
    border: 1px solid var(--border);
    border-radius: 4px;
    color: var(--text-dim);
    font-size: 9px;
    cursor: pointer;
    line-height: 1;
    padding: 1px 4px;
    opacity: 0;
    transition: opacity 0.1s, border-color 0.1s, color 0.1s;
  }
  .asset-item:hover .asset-add-timeline { opacity: 1; }
  .asset-add-timeline:hover { border-color: var(--accent); color: var(--accent); }
  .asset-item-name { font-size: 12px; color: var(--text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .asset-item-meta { font-size: 10px; color: var(--text-dim); margin-top: 2px; display: flex; gap: 8px; flex-wrap: wrap; }
  .asset-badge {
    display: inline-block;
    padding: 1px 5px;
    border-radius: 3px;
    font-size: 9px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.4px;
  }
  .drop-zone {
    border: 1.5px dashed #3a4a68;
    border-radius: 7px;
    padding: 10px;
    text-align: center;
    font-size: 11px;
    color: var(--text-dim);
    margin-bottom: 8px;
    transition: border-color 0.15s, background 0.15s;
    cursor: default;
  }
  .drop-zone.drag-over {
    border-color: var(--accent);
    background: rgba(77, 125, 255, 0.08);
    color: var(--accent);
  }
  .asset-actions { display: flex; gap: 6px; margin-top: 4px; }
  .asset-list { margin: 0 0 6px; padding: 0; list-style: none; }
  .asset-item {
    padding: 7px 8px;
    border-radius: 6px;
    border: 1px solid var(--border);
    background: #0f131b;
    margin-bottom: 5px;
    cursor: pointer;
    transition: border-color 0.1s;
  }
  .asset-item:hover { border-color: var(--accent); }
  .asset-item-name { font-size: 12px; color: var(--text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .asset-item-meta { font-size: 10px; color: var(--text-dim); margin-top: 2px; display: flex; gap: 8px; flex-wrap: wrap; }
  .asset-badge {
    display: inline-block;
    padding: 1px 5px;
    border-radius: 3px;
    font-size: 9px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.4px;
  }
  .badge-video { background: rgba(46, 120, 255, 0.25); color: #6fa3ff; }
  .badge-audio { background: rgba(203, 147, 66, 0.25); color: #e5b86a; }
  .badge-image { background: rgba(24, 180, 135, 0.25); color: #4addb5; }
  .proxy-pending { color: #a8b2c7; }
  .proxy-ready { color: #4addb5; }
  .proxy-failed { color: var(--danger); }
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
  const previewEmpty = document.querySelector<HTMLDivElement>("#preview-empty")!;
  const previewStage = document.querySelector<HTMLDivElement>("#preview-stage")!;

  let aiVisible = true;
  let playing = false;
  type PlayMode = "idle" | "stream" | "interval";
  let playMode: PlayMode = "idle";
  let lastShuttlePreviewTick = -1;
  let lastShuttlePreviewAtMs = 0;
  const SHUTTLE_PREVIEW_MIN_INTERVAL_MS = 120;
  let playTimer: number | undefined;
  let activePreviewClip: Clip | null = null;
  let frameDebounceTimer: number | undefined;
  let previewRequestSerial = 0;
  let lastJobId = "";
  let lastRenderJobId = "";
  let renderPollTimer: number | undefined;
  let nextClipId = 1000;
  let suppressHistory = false;

  const historyPast: TimelineSnapshot[] = [];
  const historyFuture: TimelineSnapshot[] = [];

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

  // Helper to turn clip id from Rust into full objects in the correct order
  function getActiveClipRefsOrdered(): ActiveClipRef[] {
    const ids = timelineUiState.activeClipIds;
    const out: ActiveClipRef[] = [];
    for (const id of ids) {
      const ref = getClipById(id);
      if (ref) {
        out.push({
          ...ref,
          asset: findRegisteredAsset(ref.clip.assetId),
          trackIndex: timelineState.tracks.indexOf(ref.track),
        });
      }
    }
    return out;
  }
  
  // Helper to intentionally pick the top video layer when clips overlap
  function getTopVideoActiveClip(): Clip | undefined {
    const refs = getActiveClipRefsOrdered();
    const video = refs.find((r) => r.track.kind === "Video");
    return video?.clip;
  }

  async function ensureTrackServerId(track: Track): Promise<string> {
    if (track.serverId) return track.serverId;
    if (!activeSequenceId) {
      throw new Error("No active sequence. Create or load a project first.");
    }
    const createdTrack = await orchestratorCreateTrack(activeSequenceId, track.kind.toLowerCase(), track.lane_index, track.name);
    track.serverId = createdTrack.id;
    return createdTrack.id;
  }

  async function persistClipToOrchestrator(track: Track, clip: Clip): Promise<void> {
    if (clip.serverId) return;
    if (!activeSequenceId) {
      throw new Error("No active sequence. Create or load a project first.");
    }
    if (!clip.assetId) {
      throw new Error(`Clip "${clip.label}" is not linked to an imported asset.`);
    }
    const trackServerId = await ensureTrackServerId(track);
    const createdClip = await orchestratorCreateClip(activeSequenceId, trackServerId, clip.assetId, clip.inTick, clip.outTick);
    clip.serverId = createdClip.id;
    clip.assetId = createdClip.asset_id;
  }

  async function placeAssetAtPlayhead(asset: Asset): Promise<Clip | null> {
    if (!activeProjectId || !activeSequenceId) {
      writeOutput("Create or load a project first (New Project), then place clips.");
      return null;
    }
  
    let track =
      timelineState.tracks.find((t) => t.id === timelineUiState.activeTrackId) ??
      timelineState.tracks[0];
    if (asset.kind === "audio") {
      track = timelineState.tracks.find((t) => t.kind === "Audio") ?? track;
    } else {
      track = timelineState.tracks.find((t) => t.kind === "Video") ?? track;
    }
    if (!track) {
      writeOutput("No timeline track available. Create a project first.");
      return null;
    }
  
    const meta = asset.meta_jsonb ?? {};
    const name = meta.name ?? asset.uri.split("/").pop() ?? asset.uri;
    const clipDurationTicks = asset.duration_ms != null
      ? Math.round((asset.duration_ms / 1000) * timelineState.fps)
      : 160;
    const inTick = Math.max(0, timelineState.playheadTick);
    const outTick = inTick + clipDurationTicks;
  
    const nextClip: Clip = {
      id: nextClipId++,
      label: name,
      inTick,
      outTick,
      color: asset.kind === "audio" ? "var(--clip-gold)" : "var(--clip-blue)",
      assetId: String(asset.id),
    };
  
    try {
      await persistClipToOrchestrator(track, nextClip);
    } catch (e) {
      writeOutput({ action: "insert_clip_error", assetId: asset.id, error: String(e) });
      return null;
    }
  
    if (outTick > timelineState.durationTicks) {
      timelineState.durationTicks = outTick + timelineState.fps * 2;
      slider.max = String(timelineState.durationTicks);
    }
    track.clips.push(nextClip);
    track.clips.sort((a, b) => a.inTick - b.inTick);
    timelineUiState.selectedClipId = nextClip.id;
    timelineUiState.activeTrackId = track.id;
    setPlayhead(inTick, { immediateNative: true });
    commitHistory("insert_clip_from_asset");
    writeOutput({
      action: "insert_clip_from_asset",
      assetId: asset.id,
      clipId: nextClip.id,
      serverClipId: nextClip.serverId,
      in_tick: inTick,
      out_tick: outTick,
    });
    return nextClip;
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
    timelineUiState.activeClipIds = snapshot.timelineUiState.activeClipIds ?? [];
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

  function updateInspector() {
    const active = getActiveClipRefsOrdered();
    const lines: string[] = [];
  
    if (active.length === 0) {
      lines.push("Active at playhead: (none)");
    } else {
      lines.push(`Active at playhead (${active.length}):`);
      for (const { track, clip } of active) {
        const srcTick = timelineState.playheadTick - clip.inTick;
        lines.push(
          `  • ${track.name} / ${clip.label} [${clip.inTick}–${clip.outTick}] src+${srcTick}f`
        );
      }
    }
  
    if (timelineUiState.selectedClipId != null) {
      const ref = getClipById(timelineUiState.selectedClipId);
      if (ref) {
        lines.push("");
        lines.push(
          `Selected: ${ref.track.name} / ${ref.clip.label} | len ${ref.clip.outTick - ref.clip.inTick}f`
        );
      }
    }
  
    inspector.textContent = lines.join("\n");
  }

  function clearPlayTimer(opts?: { skipFrameFetch?: boolean }) {
    if (playTimer) window.clearInterval(playTimer);
    playTimer = undefined;
    playing = false;
    playMode = "idle";
    lastShuttlePreviewTick = -1;
    const vid = document.querySelector<HTMLVideoElement>("#preview-video");
    if (vid) {
      vid.pause();
      vid.playbackRate = 1;
      vid.style.display = "none";
    }
    const button = document.querySelector<HTMLButtonElement>("#btn-play");
    if (button) button.textContent = "Play";
    if (!opts?.skipFrameFetch) {
      fetchFrameForPlayhead(true);
    }
  }

  let _nativeResolveTimer: number | undefined;

  function updatePlayheadNeedleOnly() {
    const tick = timelineState.playheadTick;
    timecode.textContent = tickToTimecode(tick, timelineState.fps);
    slider.value = String(tick);
    const scaledDuration = timelineState.durationTicks * timelineUiState.zoom;
    document.querySelectorAll<HTMLDivElement>(".playhead").forEach((el) => {
      el.style.left = `${((tick * timelineUiState.zoom) / scaledDuration) * 100}%`;
    });
  }

  function setPlayhead(
    next: number,
    opts?: { immediateNative?: boolean; needleOnly?: boolean },
  ) {
    timelineState.playheadTick = Math.max(
      0,
      Math.min(timelineState.durationTicks, Math.round(next))
    );

    timelineUiState.activeClipIds = timelineState.tracks
      .flatMap((t) => t.clips)
      .filter(
        (c) =>
          timelineState.playheadTick >= c.inTick &&
          timelineState.playheadTick < c.outTick
      )
      .map((c) => c.id);

    if (opts?.needleOnly) {
      updatePlayheadNeedleOnly();
    } else {
      renderTimeline({ skipInspector: true });
    }
    updateInspector();

    window.clearTimeout(_nativeResolveTimer);
    if (opts?.immediateNative || playing) {
      void resolveActiveAtPlayhead({ needleOnly: opts?.needleOnly });
    } else {
      _nativeResolveTimer = window.setTimeout(
        () => resolveActiveAtPlayhead({ needleOnly: opts?.needleOnly }),
        80,
      );
    }

    if (!playing) {
      fetchFrameForPlayhead();
    } else if (playMode === "interval") {
      maybeUpdateShuttlePreview();
    }
  }

  // Convert assetId into numeric u64 forRust
  function assetIdToNative(assetId: string | undefined): number {
    if (!assetId) return 0;
    let h = 0;
    for (let i = 0; i < assetId.length; i++) {
      h = (Math.imul(31, h) + assetId.charCodeAt(i)) | 0;
    }
    return h >>> 0;
  }

  function buildNativeSequence() {
    return {
      tracks: timelineState.tracks.map((t) => ({
        id: t.id,
        kind: t.kind === "Audio" ? "Audio" : "Video",
        lane_index: t.lane_index,
        name: t.name,
      })),
      clips: timelineState.tracks.flatMap((t) =>
        t.clips.map((c) => ({
          id: c.id,
          track_id: t.id,
          asset_id: assetIdToNative(c.assetId),
          span: { in_tick: c.inTick, out_tick: c.outTick },
          src_in_tick: 0,
        }))
      ),
    };
  }

  let resolveSerial = 0;
  async function resolveActiveAtPlayhead(opts?: { needleOnly?: boolean }) {
    const serial = ++resolveSerial;
    try {
      const result = (await timelineResolveActive({
        sequence: buildNativeSequence(),
        playhead_tick: timelineState.playheadTick,
      })) as { active_clip_ids: number[]; active_clips: unknown[] };

      if (serial !== resolveSerial) return; // stale

      timelineUiState.activeClipIds = result.active_clip_ids;
      if (opts?.needleOnly) {
        updatePlayheadNeedleOnly();
      } else {
        renderTimeline({ skipInspector: true });
      }
      updateInspector();
      if (playMode !== "interval") {
        fetchFrameForPlayhead(true);
      }
      writeOutput({
        playhead_tick: timelineState.playheadTick,
        active_clip_ids: result.active_clip_ids,
        active_clips: result.active_clips,
      });
    } catch (e) {
      writeOutput({ resolve_active_error: String(e) });
    }
  }

  function showPreviewEmpty(msg: string) {
    const previewEmpty = document.querySelector<HTMLDivElement>("#preview-empty")!;
    const label = previewEmpty.querySelector("span");
    if (label) label.textContent = msg;
    activePreviewClip = null;
    document.querySelector<HTMLVideoElement>("#preview-video")?.pause();
    document.querySelector<HTMLVideoElement>("#preview-video")!.style.display = "none";
    document.querySelector<HTMLImageElement>("#preview-frame")!.style.display = "none";
    previewEmpty.style.display = "";
  }

  function fetchFrameForPlayhead(
    immediate = false,
    opts?: { allowWhilePlaying?: boolean },
  ) {
    if (frameDebounceTimer) window.clearTimeout(frameDebounceTimer);
    const delay =
      playMode === "interval"
        ? SHUTTLE_PREVIEW_MIN_INTERVAL_MS
        : immediate
          ? 0
          : 150;
    frameDebounceTimer = window.setTimeout(async () => {
      if (playing && !opts?.allowWhilePlaying) return;

      const requestSerial = ++previewRequestSerial;
      const tick = timelineState.playheadTick;

      const foundClip = getTopVideoActiveClip();
      if (!foundClip?.assetId) {
        showPreviewEmpty(
          timelineUiState.activeClipIds.length === 0
            ? "No clip at playhead"
            : "No video at playhead",
        );
        return;
      }
      const asset = findRegisteredAsset(foundClip.assetId);
      const proxyStatus = asset?.meta_jsonb?.proxy_status;
      const proxyPath = asset?.meta_jsonb?.proxy_path;

      if (proxyStatus === "pending") { showPreviewEmpty("Proxy still transcoding…"); return; }
      if (proxyStatus === "failed" || !proxyPath) { showPreviewEmpty("Proxy unavailable"); return; }
      if (proxyStatus !== "ready") { showPreviewEmpty("No clip at playhead"); return; }

      activePreviewClip = foundClip;

      if (asset?.kind === "image") {
        document.querySelector<HTMLDivElement>("#preview-empty")!.style.display = "none";
        document.querySelector<HTMLVideoElement>("#preview-video")!.style.display = "none";
        const previewFrame = document.querySelector<HTMLImageElement>("#preview-frame")!;
        previewFrame.style.display = "";
        previewFrame.src = asset.uri;
        return;
      }

      const timeSec = Math.max(0, (tick - foundClip.inTick) / timelineState.fps);
      try {
        const b64 = await fetchFrame(proxyPath, timeSec);
        if (requestSerial !== previewRequestSerial) return;

        document.querySelector<HTMLVideoElement>("#preview-video")!.style.display = "none";
        document.querySelector<HTMLDivElement>("#preview-empty")!.style.display = "none";
        const previewFrame = document.querySelector<HTMLImageElement>("#preview-frame")!;
        previewFrame.src = `data:image/jpeg;base64,${b64}`;
        previewFrame.style.display = "";
      } catch (err) {
        if (requestSerial !== previewRequestSerial) return;
        writeOutput({ preview_frame_error: String(err), path: proxyPath, timeSec });
        showPreviewEmpty("Frame unavailable");
      }
    }, delay);
  }

  function maybeUpdateShuttlePreview(force = false) {
    if (playMode !== "interval" || !playing) return;

    const tick = timelineState.playheadTick;
    const now = performance.now();
    if (!force && now - lastShuttlePreviewAtMs < SHUTTLE_PREVIEW_MIN_INTERVAL_MS) {
      return;
    }
    lastShuttlePreviewTick = tick;
    lastShuttlePreviewAtMs = now;
    fetchFrameForPlayhead(true, { allowWhilePlaying: true });
  }

  function renderTimeline(opts?: { skipInspector?: boolean }) {
    // Auto-correct outTick for clips whose asset duration is known but was stored short
    let maxTick = 0;
    for (const track of timelineState.tracks) {
      for (const clip of track.clips) {
        if (clip.assetId) {
          const asset = findRegisteredAsset(clip.assetId);
          if (asset?.duration_ms != null) {
            const assetDurTicks = Math.round((asset.duration_ms / 1000) * timelineState.fps);
            const correctOut = clip.inTick + assetDurTicks;
            if (correctOut > clip.outTick) clip.outTick = correctOut;
          }
        }
        maxTick = Math.max(maxTick, clip.outTick);
      }
    }
    if (maxTick > 0 && maxTick + timelineState.fps * 2 > timelineState.durationTicks) {
      timelineState.durationTicks = maxTick + timelineState.fps * 2;
      slider.max = String(timelineState.durationTicks);
    }

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
        if (timelineUiState.activeClipIds.includes(clip.id)) clipNode.classList.add("active-clip");
        clipNode.style.left = `${((clip.inTick * timelineUiState.zoom) / scaledDuration) * 100}%`;
        clipNode.style.width = `${(((clip.outTick - clip.inTick) * timelineUiState.zoom) / scaledDuration) * 100}%`;
        clipNode.style.background = clip.color;
        clipNode.textContent = clip.label;
        clipNode.draggable = false;
        clipNode.addEventListener("click", (event) => {
          event.stopPropagation();
          timelineUiState.selectedClipId = clip.id;
          timelineUiState.activeTrackId = track.id;
          renderTimeline({ skipInspector: true });
          updateInspector();
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
          renderTimeline({ skipInspector: true });
          updateInspector();
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
    slider.max = String(timelineState.durationTicks);
    slider.value = String(timelineState.playheadTick);
    if (!opts?.skipInspector) {
      updateInspector();
    }
    fetchFrameForPlayhead();
  }

  function fmtDuration(ms: number | null): string {
    if (ms == null) return "";
    const s = Math.floor(ms / 1000);
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    const sec = s % 60;
    if (h > 0) return `${h}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}`;
    return `${m}:${String(sec).padStart(2, "0")}`;
  }

  async function refreshProjectAssets(): Promise<void> {
    if (!activeProjectId) {
      writeOutput("Create or load a project first.");
      return;
    }
    try {
      registeredAssets = await listProjectAssets(activeProjectId);
      renderAssetList();
      if (registeredAssets.some((a) => a.meta_jsonb?.proxy_status === "pending")) {
        startProxyPolling();
      }
      const failedProxies = registeredAssets.filter((a) => a.meta_jsonb?.proxy_status === "failed");
      const missingFiles = registeredAssets.filter(
        (a) => !a.uri || a.uri.startsWith("renderflow://"),
      );
      if (failedProxies.length) {
        writeOutput({
          action: "proxy_warning",
          message: "One or more assets have a failed proxy",
          assetIds: failedProxies.map((a) => a.id),
        });
      }
      if (missingFiles.length) {
        writeOutput({
          action: "asset_warning",
          message: "Some assets have no local file",
          assetIds: missingFiles.map((a) => a.id),
        });
      }
      writeOutput({ action: "assets_refreshed", count: registeredAssets.length });
    } catch (e) {
      writeOutput({ action: "assets_refresh_error", error: String(e) });
    }
  }

  function renderAssetList() {
    assetList.innerHTML = "";
    if (registeredAssets.length === 0) return;
    for (const asset of registeredAssets) {
      const meta = asset.meta_jsonb ?? {};
      const name = meta.name ?? asset.uri.split("/").pop() ?? asset.uri;
      const li = document.createElement("li");
      li.className = "asset-item";

      const badgeClass =
        asset.kind === "video" ? "badge-video"
        : asset.kind === "audio" ? "badge-audio"
        : asset.kind === "ai_bundle" ? "badge-image"
        : "badge-image";
      const sourceLabel = meta.source === "ai" ? '<span class="asset-badge badge-image">AI</span>' : "";
      const resMeta = meta.width && meta.height ? `${meta.width}×${meta.height}` : "";
      const durMeta = asset.duration_ms != null ? fmtDuration(asset.duration_ms) : "";
      const fpsMeta = meta.fps != null ? `${meta.fps.toFixed(2)} fps` : "";
      const proxyStatus = meta.proxy_status ?? "unavailable";
      const proxyLabel = proxyStatus === "pending" ? "⏳ proxy" : proxyStatus === "ready" ? "✓ proxy" : proxyStatus === "failed" ? "✗ proxy" : "";
      const proxyClass = proxyStatus === "ready" ? "proxy-ready" : proxyStatus === "failed" ? "proxy-failed" : "proxy-pending";

      li.innerHTML = `
        <button class="asset-remove" title="Remove from project">×</button>
        <button class="asset-add-timeline" title="Add to timeline at playhead">+ Timeline</button>
        <div class="asset-item-name" title="${asset.uri}">${name}</div>
        <div class="asset-item-meta">
          <span class="asset-badge ${badgeClass}">${asset.kind}</span>
          ${sourceLabel}
          ${durMeta ? `<span>${durMeta}</span>` : ""}
          ${resMeta ? `<span>${resMeta}</span>` : ""}
          ${fpsMeta ? `<span>${fpsMeta}</span>` : ""}
          ${proxyLabel ? `<span class="${proxyClass}">${proxyLabel}</span>` : ""}
        </div>
      `;

      li.querySelector(".asset-remove")!.addEventListener("click", (e) => {
        e.stopPropagation();
        registeredAssets = registeredAssets.filter((a) => a.id !== asset.id);
        renderAssetList();
      });


      const place = () => void placeAssetAtPlayhead(asset);

      li.querySelector(".asset-add-timeline")!.addEventListener("click", (e) => {
        e.stopPropagation();
        place();
      });
      li.addEventListener("click", () => place());

      assetList.appendChild(li);
    }
  }

  function startRenderPolling(jobId: string) {
    if (renderPollTimer) window.clearInterval(renderPollTimer);
    renderPollTimer = window.setInterval(async () => {
      try {
        const job = await getRenderJob(jobId);
        writeOutput({ action: "export_progress", ...job });
        if (job.status === "completed" && job.output_uri) {
          window.clearInterval(renderPollTimer);
          renderPollTimer = undefined;
          const streamUrl = getStreamUrl(job.output_uri);
          writeOutput({
            action: "export_complete",
            output_path: job.output_uri,
            stream_url: streamUrl,
            hint: "Output is playable via stream_url or open output_path in Finder",
          });
          fetchFrameForPlayhead(true);
        } else if (job.status === "failed") {
          window.clearInterval(renderPollTimer);
          renderPollTimer = undefined;
          writeOutput({ action: "export_failed", error: job.error ?? "render failed" });
        }
      } catch (e) {
        writeOutput({ action: "export_poll_error", error: String(e) });
      }
    }, 2000);
  }

  function startProxyPolling() {
    if (proxyPollTimer) return;
    proxyPollTimer = window.setInterval(async () => {
      const pending = registeredAssets.filter((a) => a.meta_jsonb?.proxy_status === "pending");
      if (pending.length === 0) {
        window.clearInterval(proxyPollTimer);
        proxyPollTimer = undefined;
        return;
      }
      let changed = false;
      for (const asset of pending) {
        try {
          const fresh = await getAsset(asset.id);
          if (fresh.meta_jsonb?.proxy_status !== "pending") {
            const idx = registeredAssets.findIndex((a) => a.id === asset.id);
            if (idx >= 0) { registeredAssets[idx] = fresh; changed = true; }
            if (fresh.meta_jsonb?.proxy_status === "failed") {
              writeOutput({ action: "proxy_error", assetId: asset.id, message: "Proxy transcode failed" });
            }
          }
        } catch (e) {
          writeOutput({ action: "proxy_poll_error", assetId: asset.id, error: String(e) });
        }
      }
      if (changed) {
        renderAssetList();
        fetchFrameForPlayhead(true);  // re-check preview now that a proxy may be ready
      }
    }, 3000);
  }


  async function handleImportFile(filePath: string) {
    if (!activeProjectId) {
      writeOutput("Create or load a project first, then import media.");
      return;
    }
    writeOutput(`Importing: ${filePath}`);
    try {
      const asset = await importMedia(activeProjectId, filePath);
      registeredAssets.push(asset);
      renderAssetList();
      writeOutput({ action: "import_asset", 
        id: asset.id,
        kind: asset.kind,
        duration_ms: asset.duration_ms,
        meta: asset.meta_jsonb,
        hint: "Asset added to bin — click it or press + Timeline to place at playhead",
      });
      if (asset.meta_jsonb?.proxy_status === "pending") startProxyPolling();
    } catch (e) {
      writeOutput({ action: "import_error", error: String(e) });
    }
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
      assetId: ref.clip.assetId,
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
    setPlayhead(timelineState.playheadTick + direction, { immediateNative: true });
  }

  function startIntervalShuttle(multiplier: number) {
    playMode = "interval";
    lastShuttlePreviewTick = -1;
    lastShuttlePreviewAtMs = 0;

    const vid = document.querySelector<HTMLVideoElement>("#preview-video");
    if (vid) {
      vid.pause();
      vid.style.display = "none";
    }

    playTimer = window.setInterval(() => {
      const next = timelineState.playheadTick + multiplier;
      if (next > timelineState.durationTicks) {
        setPlayhead(0, { needleOnly: true, immediateNative: true });
        clearPlayTimer({ skipFrameFetch: true });
        maybeUpdateShuttlePreview(true);
        return;
      }
      if (next < 0) {
        setPlayhead(timelineState.durationTicks, { needleOnly: true, immediateNative: true });
        clearPlayTimer({ skipFrameFetch: true });
        maybeUpdateShuttlePreview(true);
        return;
      }
      setPlayhead(next, { needleOnly: true });
    }, Math.max(15, Math.round(1000 / timelineState.fps)));
  }

  function shuttle(multiplier: number) {
    clearPlayTimer({ skipFrameFetch: true });
    if (multiplier === 0) return;
    playing = true;
    const button = document.querySelector<HTMLButtonElement>("#btn-play");
    if (button) button.textContent = "Pause";

    const clip = getTopVideoActiveClip() ?? activePreviewClip;
    const asset = findRegisteredAsset(clip?.assetId);
    const proxyPath = asset?.meta_jsonb?.proxy_path;
    const proxyReady = asset?.meta_jsonb?.proxy_status === "ready" && !!proxyPath;

    if (multiplier !== 1 || !clip || !proxyReady) {
      activePreviewClip = clip ?? null;
      startIntervalShuttle(multiplier);
      maybeUpdateShuttlePreview(true);
      return;
    }

    playMode = "stream";
    activePreviewClip = clip;

    // Real video+audio stream via orchestrator
    const previewVideo = document.querySelector<HTMLVideoElement>("#preview-video")!;
    const streamSrc = getStreamUrl(proxyPath);
    const timeSec = Math.max(0, (timelineState.playheadTick - clip.inTick) / timelineState.fps);
    writeOutput({ action: "play_start", streamSrc, timeSec });

    if (previewVideo.dataset.proxySrc !== streamSrc) {
      previewVideo.src = streamSrc;
      previewVideo.dataset.proxySrc = streamSrc;
    }
    document.querySelector<HTMLImageElement>("#preview-frame")!.style.display = "none";
    previewVideo.style.display = "";
    document.querySelector<HTMLDivElement>("#preview-empty")!.style.display = "none";

    const seekAndPlay = () => {
      previewVideo.play().catch((err) => {
        writeOutput({ play_error: String(err) });
        clearPlayTimer();
      });
    };
    const doPlay = () => {
      if (timeSec > 0.05) {
        previewVideo.currentTime = timeSec;
        previewVideo.addEventListener("seeked", seekAndPlay, { once: true });
      } else {
        seekAndPlay();
      }
    };
    if (previewVideo.readyState >= 2) {
      doPlay();
    } else {
      previewVideo.addEventListener("loadeddata", doPlay, { once: true });
    }
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

  document.querySelector("#btn-submit-job")!.addEventListener("click", async () => {
    const prompt = aiPrompt.value.trim();
    if (!prompt) {
      writeOutput("Enter an AI prompt first.");
      return;
    }
    if (!activeProjectId) {
      writeOutput("Click New Project first.");
      return;
    }
    try {
      const result = await submitAiJob(activeProjectId, prompt);
      lastJobId = result.job_id;
      document.querySelector<HTMLButtonElement>("#btn-accept-job")!.disabled = true;
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
      const acceptBtn = document.querySelector<HTMLButtonElement>("#btn-accept-job")!;
      const canAccept = result.status === "review" && Boolean(result.metadata?.output_path);
      acceptBtn.disabled = !canAccept;
      if (result.status === "review" && !result.metadata?.output_path) {
        writeOutput({
          action: "artifact_warning",
          message: result.metadata?.artifact_error ?? "AI artifact not ready — cannot accept yet",
        });
      }
    } catch (e) {
      writeOutput(e);
    }
  });

  document.querySelector("#btn-accept-job")!.addEventListener("click", async () => {
    if (!lastJobId) {
      writeOutput("Submit and refresh a job first.");
      return;
    }
    try {
      const job = await acceptAiJob(lastJobId);
      await refreshProjectAssets();
      const assetId = job.metadata?.asset_id;
      if (!assetId) {
        writeOutput({ action: "accept_error", message: "No asset_id after accept" });
        return;
      }
      const asset = findRegisteredAsset(String(assetId));
      if (!asset) {
        writeOutput({ action: "accept_error", message: "Asset not in bin after refresh", assetId });
        return;
      }
      if (asset.meta_jsonb?.proxy_status === "failed") {
        writeOutput({ action: "proxy_error", message: "Proxy transcode failed", assetId });
      } else {
        writeOutput({ 
          action: "accept_ok", 
          assetId, 
          proxy_status: asset.meta_jsonb?.proxy_status,
          hint: "Asset added to bin — click it or press + Timeline to place at playhead",
        });
      }
      document.querySelector<HTMLButtonElement>("#btn-accept-job")!.disabled = true;
    } catch (e) {
      writeOutput({ action: "accept_error", error: String(e) });
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
      const v1Server = await orchestratorCreateTrack(seq.id, "video", 0, "V1");
      const a1Server = await orchestratorCreateTrack(seq.id, "audio", 0, "A1");
      const v1Id = nextClipId++;
      const a1Id = nextClipId++;
      timelineState.tracks = [
        { id: v1Id, serverId: v1Server.id, name: "V1", kind: "Video", lane_index: 0, clips: [] },
        { id: a1Id, serverId: a1Server.id, name: "A1", kind: "Audio", lane_index: 0, clips: [] },
      ];
      timelineState.playheadTick = 0;
      timelineUiState.selectedClipId = null;
      timelineUiState.activeTrackId = v1Id;
      timelineUiState.markers = [];
      registeredAssets = [];
      renderAssetList();
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
          await persistClipToOrchestrator(track, clip);
        }
      }
      writeOutput({ action: "save_project", projectId: activeProjectId, tracks: timelineState.tracks.length });
    } catch (e) {
      writeOutput({ action: "save_error", error: String(e) });
    }
  });

  document.querySelector("#btn-export")!.addEventListener("click", async () => {
    if (!activeProjectId || !activeSequenceId) {
      writeOutput("Create or load a project first.");
      return;
    }
    const exportBtn = document.querySelector<HTMLButtonElement>("#btn-export")!;
    exportBtn.disabled = true;
    try {
      for (const track of timelineState.tracks) {
        if (!track.serverId) {
          const t = await orchestratorCreateTrack(activeSequenceId, track.kind.toLowerCase(), track.lane_index, track.name);
          track.serverId = t.id;
        }
        for (const clip of track.clips) {
          await persistClipToOrchestrator(track, clip);
        }
      }
      const job = await submitRenderJob(activeProjectId, activeSequenceId, "h264_1080p");
      lastRenderJobId = job.id;
      writeOutput({ action: "export_submitted", job });
      startRenderPolling(job.id);
    } catch (e) {
      writeOutput({ action: "export_error", error: String(e) });
    } finally {
      exportBtn.disabled = false;
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
      const project = result.items[0];

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
            assetId: c.asset_id,
            label: c.name || "Clip",
            inTick: c.in_tick,
            outTick: c.out_tick,
            color: t.track_type === "audio" ? "var(--clip-gold)" : "var(--clip-blue)",
          })),
      }));

      timelineUiState.activeTrackId = timelineState.tracks[0]?.id ?? null;

      // Grow the timeline to fit all loaded clips
      const maxOutTick = timelineState.tracks
        .flatMap((t) => t.clips)
        .reduce((m, c) => Math.max(m, c.outTick), 0);
      if (maxOutTick > timelineState.durationTicks) {
        timelineState.durationTicks = maxOutTick + timelineState.fps * 2;
      }

      const projectNameInput = document.querySelector<HTMLInputElement>("#project-name");
      if (projectNameInput) projectNameInput.value = project.name;
      await refreshProjectAssets();
      renderTimeline();
      writeOutput({ action: "load_project", projectId: project.id, tracks: tracks.length, clips: clips.length, assets: registeredAssets.length });
      resolveActiveAtPlayhead()
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

  let wasPlayingBeforeScrub = false;

  slider.addEventListener("pointerdown", () => {
    wasPlayingBeforeScrub = playing;
    if (playing) clearPlayTimer();
  });

  slider.addEventListener("pointerup", () => {
    setPlayhead(Number(slider.value), { immediateNative: true });
    if (wasPlayingBeforeScrub) {
      wasPlayingBeforeScrub = false;
      shuttle(1);
    }
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
  });

  // Tauri drag-drop: fires when files are dragged from the OS onto the window
  (async () => {
    try {
      const { getCurrentWebview } = await import("@tauri-apps/api/webview");
      await getCurrentWebview().onDragDropEvent(async (event) => {
        if (event.payload.type === "over") { dropZone.classList.add("drag-over"); return; }
        if (event.payload.type === "leave") { dropZone.classList.remove("drag-over"); return; }
        if (event.payload.type === "drop") {
          dropZone.classList.remove("drag-over");
          for (const path of event.payload.paths) {
            await handleImportFile(path);
          }
        }
      });
    } catch {
      // Not running inside Tauri (e.g. browser dev mode) — drag-drop via Tauri unavailable
    }
  })();

  const previewVideoEl = document.querySelector<HTMLVideoElement>("#preview-video")!;

  previewVideoEl.addEventListener("error", () => {
    const e = previewVideoEl.error;
    writeOutput({ preview_video_error: e ? `code ${e.code}: ${e.message}` : "unknown", src: previewVideoEl.src });
    if (playing) clearPlayTimer();
  });

  previewVideoEl.addEventListener("timeupdate", () => {
    if (!playing || !activePreviewClip) return;
    const clip = activePreviewClip;
    const newTick = clip.inTick + Math.round(previewVideoEl.currentTime * timelineState.fps);
    if (newTick >= clip.outTick) {
      clearPlayTimer({ skipFrameFetch: true });
      setPlayhead(clip.outTick, { immediateNative: true });
      return;
    }
    setPlayhead(newTick, { needleOnly: true });
  });

  previewVideoEl.addEventListener("ended", () => {
    if (!playing || !activePreviewClip) return;
    const endTick = activePreviewClip.outTick;
    clearPlayTimer({ skipFrameFetch: true });
    setPlayhead(endTick, { immediateNative: true });
  });

  renderAssetList();
  timelineUiState.activeTrackId = timelineState.tracks[0]?.id ?? null;
  renderTimeline();
  resolveActiveAtPlayhead();
}
