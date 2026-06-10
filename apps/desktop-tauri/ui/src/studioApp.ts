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
  fetchFrame,
  getStreamUrl,
  acceptAIJob,
  rejectAIJob,
  BASE,
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
              <span class="elapsed" id="elapsed">0:00.0</span>
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
          <div style="display:flex;gap:6px">
            <button class="btn btn-accept" id="btn-accept-job" type="button" disabled>Accept</button>
            <button class="btn btn-reject" id="btn-reject-job" type="button" disabled>Reject</button>
          </div>
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
    padding: 8px 8px;
    font-size: 12px;
    color: var(--text-dim);
    display: flex;
    flex-direction: column;
    justify-content: center;
    gap: 2px;
  }
  .track-name-label { font-size: 12px; color: var(--text-dim); cursor: pointer; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .track-time-indicator { font-size: 9px; color: #6fa3ff; font-variant-numeric: tabular-nums; white-space: nowrap; }
  .timeline-ruler {
    display: grid;
    grid-template-columns: 110px 1fr;
    height: 22px;
    border-bottom: 1px solid #2a3140;
    background: #0a0e18;
  }
  .timeline-ruler-label {
    border-right: 1px solid #1f2736;
    font-size: 9px;
    color: #4a5568;
    display: flex;
    align-items: center;
    padding: 0 8px;
    text-transform: uppercase;
    letter-spacing: 0.6px;
  }
  .timeline-ruler-track { position: relative; overflow: hidden; }
  .ruler-tick { position: absolute; top: 0; width: 1px; background: #2a3140; }
  .ruler-tick.major { height: 100%; background: #3a4a68; }
  .ruler-tick.minor { height: 45%; top: 55%; }
  .ruler-label { position: absolute; bottom: 3px; font-size: 9px; color: #4a5a78; transform: translateX(-50%); white-space: nowrap; pointer-events: none; }
  .ruler-playhead { position: absolute; top: 0; bottom: 0; width: 2px; background: var(--danger); opacity: 0.8; pointer-events: none; }
  .elapsed { font-size: 11px; color: #18b487; font-variant-numeric: tabular-nums; min-width: 56px; text-align: right; }
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
  .badge-ai { background: rgba(138, 84, 245, 0.25); color: #b68fff; }
  .proxy-pending { color: #a8b2c7; }
  .proxy-ready { color: #4addb5; }
  .proxy-failed { color: var(--danger); }
  .btn-accept { background: #18b487; flex: 1; }
  .btn-reject { background: #ff4e75; flex: 1; }
  .btn-accept:disabled, .btn-reject:disabled { opacity: 0.35; cursor: not-allowed; }
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
  let playTimer: number | undefined;
  let elapsedStartTime: number | undefined;
  let elapsedTimer: number | undefined;
  let elapsedAccumulatedMs = 0;
  let proxyTimeUpdateHandler: (() => void) | undefined;
  let activePreviewClip: Clip | null = null;
  let frameDebounceTimer: number | undefined;
  let previewRequestSerial = 0;
  let lastJobId = "";
  let jobEventSource: EventSource | undefined;
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
    if (elapsedTimer) {
      window.clearInterval(elapsedTimer);
      if (elapsedStartTime !== undefined) elapsedAccumulatedMs += performance.now() - elapsedStartTime;
    }
    elapsedTimer = undefined;
    elapsedStartTime = undefined;
    playing = false;
    const vid = document.querySelector<HTMLVideoElement>("#preview-video");
    if (vid) {
      if (proxyTimeUpdateHandler) {
        vid.removeEventListener("timeupdate", proxyTimeUpdateHandler);
        proxyTimeUpdateHandler = undefined;
      }
      vid.pause();
      vid.style.display = "none";
    }
    const button = document.querySelector<HTMLButtonElement>("#btn-play");
    if (button) button.textContent = "Play";
    // Re-fetch a still frame for where the user stopped
    fetchFrameForPlayhead(true);
  }

  let _nativeResolveTimer: number | undefined;

  function setPlayhead(next: number) {
    timelineState.playheadTick = Math.max(0, Math.min(timelineState.durationTicks, Math.round(next)));
    // Instant JS resolution — keeps highlights and playhead responsive on every tick
    timelineUiState.activeClipIds = timelineState.tracks
      .flatMap((t) => t.clips)
      .filter((c) => timelineState.playheadTick >= c.inTick && timelineState.playheadTick < c.outTick)
      .map((c) => c.id);
    renderTimeline();
    if (!playing) fetchFrameForPlayhead();
    // Debounced Rust engine call: fires 120 ms after scrubbing/stepping settles.
    // Gives authoritative lane-ordered active_clip_ids and updates the debug panel.
    window.clearTimeout(_nativeResolveTimer);
    _nativeResolveTimer = window.setTimeout(() => resolveActiveAtPlayhead(), 120);
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
          asset_id: 0,
          span: { in_tick: c.inTick, out_tick: c.outTick },
          src_in_tick: 0,
        }))
      ),
    };
  }

  async function resolveActiveAtPlayhead() {
    try {
      const result = await timelineResolveActive({
        sequence: buildNativeSequence(),
        playhead_tick: timelineState.playheadTick,
      }) as { active_clip_ids: number[]; active_clips: unknown[] };
      // Rust engine is authoritative for lane ordering (overlapping clips)
      timelineUiState.activeClipIds = result.active_clip_ids;
      renderTimeline();
      fetchFrameForPlayhead();
      writeOutput({ playhead_tick: timelineState.playheadTick, active_clip_ids: result.active_clip_ids, active_clips: result.active_clips });
    } catch {
      // JS fallback already applied — nothing extra needed
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

  function fetchFrameForPlayhead(immediate = false) {
    if (frameDebounceTimer) window.clearTimeout(frameDebounceTimer);
    frameDebounceTimer = window.setTimeout(async () => {
      if (playing) return;
      const tick = timelineState.playheadTick;

      // Search tracks directly — more reliable than activeClipIds which may be stale
      let foundClip: Clip | undefined;
      for (const track of timelineState.tracks) {
        foundClip = track.clips.find((c) => tick >= c.inTick && tick < c.outTick);
        if (foundClip) break;
      }

      if (!foundClip?.assetId) { showPreviewEmpty("No clip at playhead"); return; }
      const asset = registeredAssets.find((a) => a.id === foundClip!.assetId);
      const proxyStatus = asset?.meta_jsonb?.proxy_status;
      const proxyPath = asset?.meta_jsonb?.proxy_path;

      if (proxyStatus === "pending") { showPreviewEmpty("Proxy still transcoding…"); return; }
      if (proxyStatus === "failed" || !proxyPath) { showPreviewEmpty("Proxy unavailable"); return; }
      if (proxyStatus !== "ready") { showPreviewEmpty("No clip at playhead"); return; }

      if (asset?.kind === "image") {
        document.querySelector<HTMLDivElement>("#preview-empty")!.style.display = "none";
        document.querySelector<HTMLVideoElement>("#preview-video")!.style.display = "none";
        const previewFrame = document.querySelector<HTMLImageElement>("#preview-frame")!;
        previewFrame.style.display = "";
        previewFrame.src = asset.uri;
        return;
      }

      activePreviewClip = foundClip;
      const timeSec = Math.max(0, (tick - foundClip.inTick) / timelineState.fps);
      try {
        const b64 = await fetchFrame(proxyPath, timeSec);
        if (playing) return; // playback started while frame was fetching — don't clobber video
        document.querySelector<HTMLVideoElement>("#preview-video")!.style.display = "none";
        document.querySelector<HTMLDivElement>("#preview-empty")!.style.display = "none";
        const previewFrame = document.querySelector<HTMLImageElement>("#preview-frame")!;
        previewFrame.src = `data:image/jpeg;base64,${b64}`;
        previewFrame.style.display = "";
      } catch (err) {
        writeOutput({ preview_frame_error: String(err), path: proxyPath, timeSec });
        showPreviewEmpty("Frame unavailable");
      }
    }, immediate ? 0 : 150);
  }

  function renderTimeline() {
    // Auto-correct outTick for clips whose asset duration is known but was stored short
    let maxTick = 0;
    for (const track of timelineState.tracks) {
      for (const clip of track.clips) {
        if (clip.assetId) {
          const asset = registeredAssets.find((a) => a.id === clip.assetId);
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

    // ── Time ruler ───────────────────────────────────────────────────────────
    const ruler = document.createElement("div");
    ruler.className = "timeline-ruler";
    const rulerLabel = document.createElement("div");
    rulerLabel.className = "timeline-ruler-label";
    rulerLabel.textContent = "TC";
    const rulerTrack = document.createElement("div");
    rulerTrack.className = "timeline-ruler-track";

    const totalSecs = duration / timelineState.fps;
    const targetTicks = 12;
    const rawInterval = totalSecs / targetTicks;
    const intervals = [0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300];
    const majorInterval = intervals.find((i) => i >= rawInterval) ?? 300;
    const minorInterval = majorInterval / 2;

    const formatRulerLabel = (secs: number) => {
      const m = Math.floor(secs / 60);
      const s = Math.floor(secs % 60);
      return m > 0 ? `${m}:${s.toString().padStart(2, "0")}` : `${s}s`;
    };

    for (let t = 0; t <= totalSecs + minorInterval; t += minorInterval) {
      const isMajor = Math.abs(t % majorInterval) < 0.001 || Math.abs((t % majorInterval) - majorInterval) < 0.001;
      const pct = ((t * timelineState.fps) / duration) * 100;
      if (pct > 100.5) break;
      const tick = document.createElement("div");
      tick.className = `ruler-tick ${isMajor ? "major" : "minor"}`;
      tick.style.left = `${pct}%`;
      rulerTrack.appendChild(tick);
      if (isMajor && t > 0) {
        const lbl = document.createElement("span");
        lbl.className = "ruler-label";
        lbl.style.left = `${pct}%`;
        lbl.textContent = formatRulerLabel(t);
        rulerTrack.appendChild(lbl);
      }
    }

    const rulerPlayhead = document.createElement("div");
    rulerPlayhead.className = "ruler-playhead";
    rulerPlayhead.style.left = `${((timelineState.playheadTick) / duration) * 100}%`;
    rulerTrack.appendChild(rulerPlayhead);
    ruler.append(rulerLabel, rulerTrack);
    timelineGrid.appendChild(ruler);
    // ─────────────────────────────────────────────────────────────────────────

    for (const track of timelineState.tracks) {
      const row = document.createElement("div");
      row.className = "track-row";
      if (track.id === timelineUiState.activeTrackId) row.classList.add("active");

      const name = document.createElement("div");
      name.className = "track-name";

      const nameLabel = document.createElement("span");
      nameLabel.className = "track-name-label";
      nameLabel.textContent = `${track.name} (${track.kind})`;
      nameLabel.addEventListener("click", () => {
        timelineUiState.activeTrackId = track.id;
        renderTimeline();
      });
      name.appendChild(nameLabel);

      {
        const clipAtHead = track.clips.find(
          (c) => timelineState.playheadTick >= c.inTick && timelineState.playheadTick < c.outTick
        );
        if (clipAtHead) {
          const posInClip = (timelineState.playheadTick - clipAtHead.inTick) / timelineState.fps;
          const clipDur = (clipAtHead.outTick - clipAtHead.inTick) / timelineState.fps;
          const timeIndicator = document.createElement("span");
          timeIndicator.className = "track-time-indicator";
          timeIndicator.textContent = `${posInClip.toFixed(1)}s / ${clipDur.toFixed(1)}s`;
          name.appendChild(timeIndicator);
        }
      }

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
    slider.max = String(timelineState.durationTicks);
    slider.value = String(timelineState.playheadTick);
    updateInspector();
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

  function renderAssetList() {
    assetList.innerHTML = "";
    if (registeredAssets.length === 0) return;
    for (const asset of registeredAssets) {
      const meta = asset.meta_jsonb ?? {};
      const name = meta.name ?? asset.uri.split("/").pop() ?? asset.uri;
      const li = document.createElement("li");
      li.className = "asset-item";

      const badgeClass = asset.kind === "video" ? "badge-video" : asset.kind === "audio" ? "badge-audio" : "badge-image";
      const resMeta = meta.width && meta.height ? `${meta.width}×${meta.height}` : "";
      const durMeta = asset.duration_ms != null ? fmtDuration(asset.duration_ms) : "";
      const fpsMeta = meta.fps != null ? `${meta.fps.toFixed(2)} fps` : "";
      const proxyStatus = meta.proxy_status ?? "unavailable";
      const proxyLabel = proxyStatus === "pending" ? "⏳ proxy" : proxyStatus === "ready" ? "✓ proxy" : proxyStatus === "failed" ? "✗ proxy" : proxyStatus === "unavailable" && meta.ai_generated ? "✗ proxy" : "";
      const proxyClass = proxyStatus === "ready" ? "proxy-ready" : proxyStatus === "failed" || (proxyStatus === "unavailable" && meta.ai_generated) ? "proxy-failed" : "proxy-pending";
      const aiBadge = meta.ai_generated ? `<span class="asset-badge badge-ai">AI</span>` : "";

      li.innerHTML = `
        <button class="asset-remove" title="Remove from project">×</button>
        <div class="asset-item-name" title="${asset.uri}">${name}</div>
        <div class="asset-item-meta">
          <span class="asset-badge ${badgeClass}">${asset.kind}</span>
          ${aiBadge}
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


      li.addEventListener("click", async () => {
        const track = timelineState.tracks.find((t) => t.id === timelineUiState.activeTrackId) ?? timelineState.tracks[0];
        if (!track) return;
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
          assetId: asset.id,
        };
        try {
          await persistClipToOrchestrator(track, nextClip);
        } catch (e) {
          writeOutput({ action: "insert_clip_error", assetId: asset.id, error: String(e) });
          return;
        }
        commitHistory("insert_clip_from_asset");
        // Extend the timeline so the full clip fits
        if (outTick > timelineState.durationTicks) {
          timelineState.durationTicks = outTick + timelineState.fps * 2;
          slider.max = String(timelineState.durationTicks);
        }
        track.clips.push(nextClip);
        track.clips.sort((a, b) => a.inTick - b.inTick);
        timelineUiState.selectedClipId = nextClip.id;
        timelineUiState.activeTrackId = track.id;
        renderTimeline();
        fetchFrameForPlayhead(true);
        writeOutput({ action: "insert_clip_from_asset", assetId: asset.id, clipId: nextClip.id, serverClipId: nextClip.serverId });
      });

      assetList.appendChild(li);
    }
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
          }
        } catch { /* ignore */ }
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
      writeOutput({ action: "import_asset", id: asset.id, kind: asset.kind, duration_ms: asset.duration_ms, meta: asset.meta_jsonb });
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
    setPlayhead(timelineState.playheadTick + direction);
  }

  function startIntervalShuttle(multiplier: number) {
    playTimer = window.setInterval(() => {
      const next = timelineState.playheadTick + multiplier;
      if (next > timelineState.durationTicks) { elapsedAccumulatedMs = 0; setPlayhead(0); return; }
      if (next < 0) { elapsedAccumulatedMs = 0; setPlayhead(timelineState.durationTicks); return; }
      setPlayhead(next);
    }, Math.max(15, Math.round(1000 / timelineState.fps)));
  }

  function shuttle(multiplier: number) {
    clearPlayTimer();
    if (multiplier === 0) return;
    playing = true;
    const button = document.querySelector<HTMLButtonElement>("#btn-play");
    if (button) button.textContent = "Pause";

    elapsedStartTime = performance.now();
    elapsedTimer = window.setInterval(() => {
      const secs = (elapsedAccumulatedMs + performance.now() - (elapsedStartTime ?? performance.now())) / 1000;
      const m = Math.floor(secs / 60);
      const s = (secs % 60).toFixed(1).padStart(4, "0");
      const elapsedEl = document.querySelector<HTMLSpanElement>("#elapsed");
      if (elapsedEl) elapsedEl.textContent = `${m}:${s}`;
    }, 100);

    const clip = activePreviewClip;
    const asset = clip ? registeredAssets.find((a) => a.id === clip.assetId) : null;
    const proxyPath = asset?.meta_jsonb?.proxy_path;

    if (multiplier !== 1 || !clip || !proxyPath || asset?.meta_jsonb?.proxy_status !== "ready") {
      startIntervalShuttle(multiplier);
      return;
    }

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

    // Sync playhead tick + time indicator while video plays natively.
    // currentTime is position within the proxy file; clip.inTick is where it sits on the timeline.
    const clipStartTick = clip.inTick;
    if (proxyTimeUpdateHandler) previewVideo.removeEventListener("timeupdate", proxyTimeUpdateHandler);
    proxyTimeUpdateHandler = () => {
      if (!playing) return;
      const newTick = clipStartTick + Math.round(previewVideo.currentTime * timelineState.fps);
      timelineState.playheadTick = Math.max(0, Math.min(timelineState.durationTicks, newTick));
      timelineUiState.activeClipIds = timelineState.tracks
        .flatMap((t) => t.clips)
        .filter((c) => timelineState.playheadTick >= c.inTick && timelineState.playheadTick < c.outTick)
        .map((c) => c.id);
      slider.value = String(timelineState.playheadTick);
      renderTimeline();
    };
    previewVideo.addEventListener("timeupdate", proxyTimeUpdateHandler);

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

  const JOB_TERMINAL = new Set(["completed", "failed", "committed", "rejected"]);

  const btnAccept = document.querySelector<HTMLButtonElement>("#btn-accept-job")!;
  const btnReject = document.querySelector<HTMLButtonElement>("#btn-reject-job")!;

  function updateJobButtons(status: string) {
    btnAccept.disabled = !["review", "committed"].includes(status);
    btnReject.disabled = !["review", "committed", "accepted"].includes(status);
  }

  function stopJobEvents() {
    if (jobEventSource) { jobEventSource.close(); jobEventSource = undefined; }
  }

  function startJobEvents(jobId: string) {
    stopJobEvents();
    // Open SSE first so we don't miss events that fire between now and the fetch below
    jobEventSource = new EventSource(`${BASE}/v1/events`);
    jobEventSource.onmessage = async (event) => {
      try {
        const data = JSON.parse(event.data) as { job_id?: string; status?: string };
        if (data.job_id !== jobId) return;
        const result = await getAiJob(jobId);
        writeOutput(result);
        updateJobButtons(result.status);
        if (JOB_TERMINAL.has(result.status)) stopJobEvents();
      } catch { /* ignore malformed events */ }
    };
    jobEventSource.onerror = () => stopJobEvents();
    // Immediately fetch current state — the mock finishes before SSE can connect
    getAiJob(jobId).then((result) => {
      writeOutput(result);
      updateJobButtons(result.status);
      if (JOB_TERMINAL.has(result.status)) { stopJobEvents(); return; }
      // Not terminal yet — schedule one follow-up fetch to catch fast mock completion.
      // Real pipelines will get updates via SSE instead.
      window.setTimeout(async () => {
        try {
          const r = await getAiJob(jobId);
          writeOutput(r);
          updateJobButtons(r.status);
          if (JOB_TERMINAL.has(r.status)) stopJobEvents();
        } catch { /* SSE will handle real updates */ }
      }, 500);
    }).catch(() => { /* SSE will still deliver if fetch fails */ });
  }

  document.querySelector("#btn-accept-job")!.addEventListener("click", async () => {
    if (!lastJobId) return;
    try {
      const result = await acceptAIJob(lastJobId);
      writeOutput(result);
      updateJobButtons(result.status);
      stopJobEvents();

      if (result.result_asset_id) {
        try {
          const asset = await getAsset(result.result_asset_id);
          if (!registeredAssets.find((a) => a.id === asset.id)) {
            registeredAssets.push(asset);
            renderAssetList();
          }
          if (asset.meta_jsonb?.proxy_status === "pending") startProxyPolling();

          const track = timelineState.tracks.find((t) => t.id === timelineUiState.activeTrackId) ?? timelineState.tracks[0];
          if (track) {
            const clipDurationTicks = asset.duration_ms != null
              ? Math.round((asset.duration_ms / 1000) * timelineState.fps)
              : 240;
            const inTick = Math.max(0, timelineState.playheadTick);
            const outTick = inTick + clipDurationTicks;
            const meta = asset.meta_jsonb ?? {};
            const label = (meta.name ?? `AI · ${result.prompt}`).slice(0, 40);
            const nextClip: Clip = {
              id: nextClipId++,
              label,
              inTick,
              outTick,
              color: "var(--clip-purple)",
              assetId: asset.id,
            };
            try { await persistClipToOrchestrator(track, nextClip); } catch { /* no active sequence — local only */ }
            commitHistory("accept_ai_asset");
            if (outTick > timelineState.durationTicks) {
              timelineState.durationTicks = outTick + timelineState.fps * 2;
              slider.max = String(timelineState.durationTicks);
            }
            track.clips.push(nextClip);
            track.clips.sort((a, b) => a.inTick - b.inTick);
            timelineUiState.selectedClipId = nextClip.id;
            timelineUiState.activeTrackId = track.id;
            renderTimeline();
            fetchFrameForPlayhead(true);
            writeOutput({ action: "accept_ai_asset", assetId: asset.id, clipId: nextClip.id, inTick, outTick });
          }
        } catch (e) {
          writeOutput({ accept_asset_error: String(e) });
        }
      }
    } catch (e) {
      writeOutput({ accept_error: String(e) });
    }
  });

  document.querySelector("#btn-reject-job")!.addEventListener("click", async () => {
    if (!lastJobId) return;
    try {
      const result = await rejectAIJob(lastJobId);
      writeOutput(result);
      updateJobButtons(result.status);
      stopJobEvents();
    } catch (e) {
      writeOutput({ reject_error: String(e) });
    }
  });

  document.querySelector("#btn-submit-job")!.addEventListener("click", async () => {
    if (!activeProjectId) {
      writeOutput("Create or load a project first before submitting an AI job.");
      return;
    }
    const prompt = aiPrompt.value.trim();
    if (!prompt) {
      writeOutput("Enter an AI prompt first.");
      return;
    }
    try {
      const result = await submitAiJob(activeProjectId, prompt);
      lastJobId = result.job_id;
      updateJobButtons(result.status);
      writeOutput({ submitted: result, status: result.status });
      startJobEvents(lastJobId);
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
      try {
        registeredAssets = await listProjectAssets(project.id);
        renderAssetList();
        if (registeredAssets.some((a) => a.meta_jsonb?.proxy_status === "pending")) startProxyPolling();
      } catch { /* orchestrator may not have assets yet */ }
      renderTimeline();
      writeOutput({ action: "load_project", projectId: project.id, tracks: tracks.length, clips: clips.length, assets: registeredAssets.length });
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

  document.querySelector("#btn-timeline")!.addEventListener("click", async () => {
    await resolveActiveAtPlayhead();
    renderTimeline();
    fetchFrameForPlayhead();
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

  // Sync timeline playhead needle during video playback without rebuilding the whole grid
  previewVideoEl.addEventListener("timeupdate", () => {
    if (!playing || !activePreviewClip) return;
    const clip = activePreviewClip;
    const newTick = clip.inTick + Math.round(previewVideoEl.currentTime * timelineState.fps);
    if (newTick >= clip.outTick) {
      clearPlayTimer();
      setPlayhead(clip.outTick);
      return;
    }
    timelineState.playheadTick = newTick;
    timecode.textContent = tickToTimecode(newTick, timelineState.fps);
    slider.value = String(newTick);
    document.querySelectorAll<HTMLDivElement>(".playhead").forEach((el) => {
      const scaledDuration = timelineState.durationTicks * timelineUiState.zoom;
      el.style.left = `${((newTick * timelineUiState.zoom) / scaledDuration) * 100}%`;
    });
  });

  previewVideoEl.addEventListener("ended", () => {
    if (playing) clearPlayTimer();
  });

  renderAssetList();
  timelineUiState.activeTrackId = timelineState.tracks[0]?.id ?? null;
  renderTimeline();
}
