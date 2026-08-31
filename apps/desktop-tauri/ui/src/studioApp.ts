// ============================================================
// studioApp.ts — Renderflow Studio
// Bootstrap and orchestrate the full UI (home + studio views).
// Logic is delegated to modular ops/ and renderer/ files.
// ============================================================

import type { StudioState, HistoryStack } from "./state";
import {
  createInitialState,
  createHistoryStack,
  resetProjectState,
} from "./state";
import type { ProjectTemplate } from "./types";
import { PROJECT_TEMPLATES } from "./types";
import {
  commitHistory,
  undoHistory,
  redoHistory,
  snapshotState,
} from "./ops/history";
import { saveProject } from "./persistence";
import {
  tickToTimecode,
  seek,
  jog,
  play,
  pause,
  stop,
  shuttle,
} from "./ops/transport";
import {
  getClipById,
  splitClip,
  deleteClip,
  moveClip,
  trimClip,
  insertAssetIntoVideoTrack,
  rippleDeleteClip,
  duplicateClip,
  snapTick,
} from "./ops/clips";
import { insertAcceptedClip, ServerSyncError } from "./ops/aiAccept";
import { launchAiProject } from "./ops/aiLaunch";
import { runExport } from "./ops/export";
import { addMarker, jumpToNextMarker } from "./ops/markers";
import {
  registerAsset,
  updateAsset,
  startProxyPolling,
  stopProxyPolling,
} from "./ops/assets";
import { renderTimeline } from "./renderer/timeline";
import type { TimelineCallbacks } from "./renderer/timeline";
import { renderAssetList } from "./renderer/assets";
import { updateInspector } from "./renderer/inspector";
import { renderHomeProjects, homeViewHtml } from "./renderer/home";
import type { HomeCallbacks } from "./renderer/home";
import { brandHtml } from "./renderer/brand";
import { registerHotkeys } from "./hotkeys";
import type { HotkeyDispatch } from "./hotkeys";
import {
  orchestratorHealth,
  orchestratorListProjects,
  orchestratorListSequences,
  orchestratorCreateProject,
  orchestratorCreateSequence,
  orchestratorDeleteProject,
  orchestratorCreateTrack,
  orchestratorDeleteTrack,
  orchestratorListTracks,
  orchestratorListClips,
  orchestratorReplaceClips,
  orchestratorCreateClip,
  submitRenderJob,
  getRenderJob,
  submitAiJob,
  getAiJob,
  acceptAiJob,
  rejectAIJob,
  importMedia,
  listProjectAssets,
  getAsset,
  fetchFrame,
  getStreamUrl,
  type Project,
  type Asset,
  type AIJob,
} from "./backendApi";

// ── buildStyle: inject full application CSS ──
function buildStyle(): void {
  const style = document.createElement("style");
  style.textContent = `
:root {
  --bg: #0d0f16; --bg-soft: #141720; --bg-raised: #1a1e2a;
  --border: #252c3d; --border-subtle: #1e2436;
  --text: #eef1f9; --text-dim: #8a95b0; --text-muted: #4f5a74;
  --accent: #4d7dff; --accent-glow: rgba(77,125,255,0.15); --accent-hover: #6390ff;
  --danger: #f04d6e; --sidebar-width: 280px; --activity-bar-width: 48px;
}
body {
  margin:0; font-family:"Inter","Segoe UI",system-ui,sans-serif;
  background:var(--bg); color:var(--text); -webkit-font-smoothing:antialiased;
}
.studio{min-height:100vh;display:flex;flex-direction:column}
.topbar{
  border-bottom:1px solid var(--border-subtle); display:flex; align-items:center;
  justify-content:space-between; padding:10px 16px;
  background:rgba(13,15,22,0.95); backdrop-filter:blur(12px); z-index:100; position:relative;
}
.brand{display:flex;align-items:center;gap:10px}
.brand-logo{flex-shrink:0}
.brand-text{font-size:15px;font-weight:700;letter-spacing:-0.2px}
.brand-sub{font-weight:400;color:var(--text-dim)}
.toolbar{display:flex;gap:8px}
.studio-body{flex:1;display:flex;flex-direction:column;min-height:0}
.workspace{
  display:grid; grid-template-columns:var(--activity-bar-width) var(--sidebar-width) 1fr;
  grid-template-rows:1fr; flex:1; min-height:0;
}
.activity-bar{
  background:var(--bg); border-right:1px solid var(--border-subtle);
  display:flex; flex-direction:column; align-items:center; padding:8px 0; gap:4px; z-index:10;
  overflow-y:auto;
}
.activity-bar::-webkit-scrollbar{display:none}
.activity-btn{
  width:36px;height:36px;border:none;border-radius:8px;background:none;
  color:var(--text-muted);cursor:pointer;display:grid;place-items:center;
  transition:background 0.15s,color 0.15s;
}
.activity-btn:hover{background:var(--bg-raised);color:var(--text-dim)}
.activity-btn.active{background:var(--accent-glow);color:var(--accent)}
.activity-spacer{flex:1;min-height:0}
.panel.ai-hidden{display:none}
.panel,.center{border-right:1px solid var(--border-subtle);background:var(--bg-soft)}
.panel{padding:14px 12px;overflow-y:auto;overflow-x:hidden}
#ai-mode-select{width:100%;background:#0f131b;border:1px solid var(--border);color:var(--text);border-radius:6px;padding:6px;margin-bottom:8px}
.ai-job-status{margin-top:10px;padding:8px;border:1px solid var(--border-subtle);border-radius:6px;background:#0f131b;font-size:11px;color:var(--text-dim);white-space:pre-wrap}
.export-status{font-size:11px;color:var(--text-dim);max-width:340px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.panel-title{
  font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:1.2px;
  color:var(--text-muted);margin-bottom:12px;padding-bottom:8px;
  border-bottom:1px solid var(--border-subtle);
}
.project-meta{display:grid;gap:8px;margin-bottom:12px}
.project-meta label{font-size:12px;color:var(--text-dim);display:grid;gap:4px}
.quick-actions{display:grid;gap:6px;margin-bottom:12px}
.project-meta input,textarea{
  background:#0f131b;border:1px solid var(--border);color:var(--text);
  border-radius:6px;padding:8px;
}
.center{display:grid;grid-template-rows:1fr 290px}
.monitor{padding:12px;border-bottom:1px solid var(--border);display:grid;grid-template-rows:auto 1fr}
.monitor-head,.timeline-head{display:flex;justify-content:space-between;align-items:center;gap:10px}
.monitor-head h3,.timeline-head h3{margin:0;font-size:12px;font-weight:700;letter-spacing:0.5px;text-transform:uppercase;color:var(--text-dim)}
.preview{margin-top:10px;border:1px solid var(--border);border-radius:10px;position:relative;overflow:hidden;background:#080a10;box-shadow:inset 0 0 30px rgba(0,0,0,0.4)}
.preview-overlay{position:absolute;inset:0;display:grid;place-items:center;align-content:center;gap:10px;color:var(--text-dim);font-size:12px;padding:16px;background:rgba(13,17,25,0.82);pointer-events:none}
.preview-overlay .btn{pointer-events:auto}
#preview-frame{display:none;position:absolute;inset:0;width:100%;height:100%;object-fit:contain;border-radius:10px}
#preview-video{display:none;position:absolute;inset:0;width:100%;height:100%;object-fit:contain;border-radius:10px}
.timeline{padding:12px;background:#111621}
.timeline-controls{display:flex;align-items:center;gap:6px;width:64%}
.timeline-grid{margin-top:10px;border:1px solid var(--border);border-radius:8px;overflow:hidden;background:#0d1119;user-select:none}
.hint{font-size:10px;color:var(--text-muted);padding:4px 12px;background:var(--bg);border-bottom:1px solid var(--border-subtle);letter-spacing:0.3px}
.track-row{display:grid;grid-template-columns:110px 1fr;min-height:46px;border-bottom:1px solid #1f2736}
.track-name{border-right:1px solid #1f2736;padding:8px;font-size:12px;color:var(--text-dim);display:flex;align-items:center;justify-content:space-between;gap:4px}
.track-name-label{cursor:pointer}
.track-delete{background:none;border:none;color:var(--text-muted);font-size:16px;cursor:pointer;opacity:0;padding:2px 6px;border-radius:4px;transition:opacity 0.15s,color 0.15s}
.track-row:hover .track-delete{opacity:1}
.track-delete:hover{color:var(--danger)}
.track-lane{position:relative}
.marker{position:absolute;top:0;bottom:0;width:1px;background:rgba(255,219,120,0.9);pointer-events:none}
.clip{position:absolute;top:8px;bottom:8px;border-radius:6px;padding:6px 8px;font-size:11px;color:#f4f7ff;overflow:hidden;white-space:nowrap;text-overflow:ellipsis;border:1px solid rgba(255,255,255,0.18);touch-action:none}
.trim-handle{position:absolute;top:0;bottom:0;width:6px;background:rgba(240,246,255,0.45);cursor:ew-resize}
.trim-handle.left{left:0;border-radius:6px 0 0 6px}
.trim-handle.right{right:0;border-radius:0 6px 6px 0}
.clip.selected{outline:2px solid #eaf1ff;box-shadow:0 0 0 2px rgba(83,129,255,0.6)}
.track-row.active .track-name{color:#f8fcff;background:rgba(77,125,255,0.15)}
.playhead{position:absolute;top:0;bottom:0;width:2px;background:var(--danger);box-shadow:0 0 8px rgba(255,78,117,0.7);pointer-events:none}
.ai-mode{color:var(--text-dim);font-size:12px;margin-bottom:8px}
.stack{display:grid;gap:6px;margin:8px 0}
.btn{background:var(--accent);color:#fff;border:none;border-radius:6px;padding:7px 14px;font-size:12px;font-weight:600;cursor:pointer;transition:background 0.15s,box-shadow 0.15s,opacity 0.15s;white-space:nowrap;letter-spacing:0.1px}
.btn:hover{background:var(--accent-hover);box-shadow:0 0 0 3px var(--accent-glow)}
.btn:active{opacity:0.8}
.btn.subtle{background:rgba(255,255,255,0.05);color:var(--text-dim);border:1px solid var(--border)}
.btn.subtle:hover{background:rgba(255,255,255,0.09);color:var(--text);border-color:var(--border)}
.btn.narrow{padding:7px 10px}
.btn.icon{min-width:56px}
#playhead-slider{width:56%}
.timecode{min-width:110px;text-align:right;color:var(--text-dim);font-variant-numeric:tabular-nums}
.elapsed{font-size:11px;color:#18b487;font-variant-numeric:tabular-nums;min-width:56px;text-align:right}
pre{background:#0f131b;border:1px solid var(--border);border-radius:8px;padding:8px;font-size:11px;overflow:auto;max-height:230px;white-space:pre-wrap}
.inspector{margin:8px 0;padding:8px;border:1px solid var(--border);border-radius:8px;background:#0f131b;font-size:12px;color:var(--text-dim);white-space:pre-line}
.drop-zone{border:1.5px dashed #3a4a68;border-radius:7px;padding:10px;text-align:center;font-size:11px;color:var(--text-dim);margin-bottom:8px;transition:border-color 0.15s,background 0.15s;cursor:default}
.drop-zone.drag-over{border-color:var(--accent);background:rgba(77,125,255,0.08);color:var(--accent)}
.asset-actions{display:flex;gap:6px;margin-top:4px}
.asset-list{margin:0 0 6px;padding:0;list-style:none}
.asset-item{padding:7px 8px;border-radius:6px;border:1px solid var(--border);background:#0f131b;margin-bottom:5px;cursor:pointer;transition:border-color 0.1s;position:relative}
.asset-item:hover{border-color:var(--accent)}
.asset-item-name{font-size:12px;color:var(--text);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.asset-item-meta{font-size:10px;color:var(--text-dim);margin-top:2px;display:flex;gap:8px;flex-wrap:wrap}
.asset-badge{display:inline-block;padding:1px 5px;border-radius:3px;font-size:9px;font-weight:600;text-transform:uppercase;letter-spacing:0.4px}
.badge-video{background:rgba(46,120,255,0.25);color:#6fa3ff}
.badge-audio{background:rgba(203,147,66,0.25);color:#e5b86a}
.badge-image{background:rgba(24,180,135,0.25);color:#4addb5}
.proxy-pending{color:#a8b2c7}.proxy-ready{color:#4addb5}.proxy-failed{color:var(--danger)}
.btn-accept{background:#18b487;flex:1}.btn-reject{background:#ff4e75;flex:1}
.btn-accept:disabled,.btn-reject:disabled{opacity:0.35;cursor:not-allowed}
/* modal */
.modal-overlay{position:fixed;inset:0;background:rgba(0,0,0,0.6);backdrop-filter:blur(4px);display:flex;align-items:center;justify-content:center;z-index:1000}
.modal{background:#181c24;border:1px solid var(--border);border-radius:14px;padding:24px;width:580px;max-width:92vw;box-shadow:0 24px 64px rgba(0,0,0,0.6)}
.modal-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:4px}
.modal-header h2{margin:0;font-size:16px;font-weight:600}
.modal-close{background:none;border:none;color:var(--text-dim);font-size:20px;cursor:pointer;padding:0 4px;line-height:1}
.modal-close:hover{color:var(--text)}
.modal-sub{color:var(--text-dim);font-size:12px;margin:0 0 16px}
.modal-actions{display:flex;justify-content:flex-end;gap:8px;margin-top:18px}
.modal-error{background:#0f131b;border:1px solid var(--border);border-radius:8px;padding:10px;
  font-family:ui-monospace,monospace;font-size:11px;color:var(--text-dim);
  max-height:120px;overflow:auto;word-break:break-word;white-space:pre-wrap}
/* toasts — stacked bottom-right, below the modal layer */
#toast-host{position:fixed;right:16px;bottom:16px;z-index:900;display:flex;
  flex-direction:column;gap:8px;align-items:flex-end;pointer-events:none}
.toast{pointer-events:auto;cursor:pointer;max-width:380px;padding:10px 14px;border-radius:8px;
  font-size:12px;border:1px solid var(--border);background:#181c24;color:var(--text);
  box-shadow:0 10px 30px rgba(0,0,0,0.5);word-break:break-word}
.toast-ok{border-color:#18b487}
.toast-error{border-color:#ff6b6b}
.template-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:10px}
.template-card{background:#0f131b;border:1px solid var(--border);border-radius:10px;padding:14px;cursor:pointer;transition:border-color 0.15s,background 0.15s}
.template-card:hover{border-color:var(--accent);background:rgba(77,125,255,0.07)}
.template-name{font-size:13px;font-weight:600;margin-bottom:5px}
.template-desc{font-size:11px;color:var(--text-dim);margin-bottom:10px;line-height:1.45}
.template-tracks{display:flex;gap:4px;flex-wrap:wrap}
.track-badge{display:inline-block;padding:2px 7px;border-radius:4px;font-size:10px;font-weight:600;letter-spacing:0.3px}
.track-badge.video{background:rgba(46,120,255,0.22);color:#6fa3ff}
.track-badge.audio{background:rgba(203,147,66,0.22);color:#e5b86a}
/* devtools */
.devtools-drawer{background:var(--bg);border-top:1px solid var(--border);height:260px;display:flex;flex-direction:column;overflow:hidden;z-index:50;flex-shrink:0}
.devtools-header{display:flex;align-items:center;justify-content:space-between;padding:8px 14px;background:var(--bg-soft);border-bottom:1px solid var(--border-subtle);font-size:11px;font-weight:600;color:var(--text-dim);letter-spacing:0.5px;flex-shrink:0}
.devtools-out{flex:1;margin:0;border:none;border-radius:0;background:var(--bg);overflow:auto;padding:10px 14px;font-size:11px;color:#7adf9f;white-space:pre-wrap;max-height:none}
/* home */
.home-view{min-height:100vh;display:flex;flex-direction:column}
.topbar-home{background:rgba(13,15,22,0.98)}
.devtools-btn.dev-hidden{display:none!important}
.home-main{flex:1;display:flex;flex-direction:column;align-items:center;padding:60px 24px 40px}
.home-hero{text-align:center;max-width:640px;margin-bottom:48px}
.home-hero h1{font-size:40px;font-weight:800;letter-spacing:-1px;margin:0 0 12px;line-height:1.2}
/* Render and Flow read as two words: each gets its own color. */
.word-render{color:#4d7dff}
.word-flow{color:#c084fc}
.hero-studio{color:var(--text-dim);font-weight:600}
.hero-sub{font-size:15px;color:var(--text-dim);line-height:1.55;margin:0 0 24px}
/* prompt entry */
.prompt-box{background:var(--bg-raised);border:1px solid var(--border);border-radius:14px;padding:12px;text-align:left;transition:border-color 0.15s}
.prompt-box:focus-within{border-color:var(--accent);box-shadow:0 0 0 3px var(--accent-glow)}
#home-prompt{width:100%;box-sizing:border-box;background:none;border:none;color:var(--text);font-family:inherit;font-size:15px;resize:none;outline:none;padding:6px}
.prompt-actions{display:flex;justify-content:space-between;align-items:center;gap:8px;margin-top:6px}
.suggestions{display:flex;flex-wrap:wrap;gap:8px;justify-content:center;margin-top:16px}
.suggestion-chip{background:rgba(255,255,255,0.04);border:1px solid var(--border);color:var(--text-dim);border-radius:999px;padding:7px 14px;font-size:12px;font-family:inherit;cursor:pointer;transition:border-color 0.15s,color 0.15s,background 0.15s}
.suggestion-chip:hover{border-color:var(--accent);color:var(--text);background:rgba(77,125,255,0.08)}
.prompt-status{font-size:12px;color:var(--text-dim);margin-top:14px;min-height:16px}
.prompt-status.error{color:var(--danger)}
.home-projects{width:100%;max-width:900px}
.home-section-header{display:flex;align-items:baseline;justify-content:space-between;margin-bottom:16px;padding-bottom:10px;border-bottom:1px solid var(--border-subtle)}
.home-section-header h2{margin:0;font-size:16px;font-weight:600}
.home-project-count{font-size:12px;color:var(--text-dim)}
.home-project-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:12px}
.home-project-card{background:var(--bg-raised);border:1px solid var(--border);border-radius:10px;padding:16px;cursor:pointer;transition:border-color 0.15s,background 0.15s,transform 0.1s}
.home-project-card:hover{border-color:var(--accent);background:rgba(77,125,255,0.06);transform:translateY(-1px)}
.home-project-card-name{font-size:14px;font-weight:600;margin-bottom:6px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.home-project-card-meta{font-size:11px;color:var(--text-dim);display:flex;gap:12px;flex-wrap:wrap}
.home-project-card-meta span{display:flex;align-items:center;gap:4px}
.home-project-card-actions{margin-top:10px;display:flex;gap:8px}
.home-empty,.home-loading,.home-error{text-align:center;padding:40px 16px;color:var(--text-dim);grid-column:1/-1}
.home-error{color:var(--danger)}.home-error .btn{margin-top:10px}
`;
  document.head.appendChild(style);
}

// ── buildDom: inject full application HTML into the root element ──
function buildDom(root: HTMLElement): void {
  root.innerHTML = `
<!-- HOME VIEW -->
${homeViewHtml()}

<!-- STUDIO VIEW -->
<div id="studio-view" class="studio-view" style="display:none">
<div class="studio">
  <header class="topbar">
    ${brandHtml("brand-studio", true)}
    <div class="toolbar">
      <button class="btn subtle" id="btn-home-nav" type="button">Home</button>
      <button class="btn subtle" id="btn-toggle-theme" type="button">Theme</button>
      <button class="btn subtle" id="btn-undo" type="button">Undo</button>
      <button class="btn subtle" id="btn-redo" type="button">Redo</button>
      <button class="btn" id="btn-save-project" type="button">Save</button>
      <button class="btn" id="btn-export" type="button">Export</button>
      <span id="export-status" class="export-status"></span>
    </div>
  </header>
  <div class="studio-body">
  <div class="workspace" id="workspace">
    <nav class="activity-bar" id="activity-bar">
      <button class="activity-btn active" id="act-explorer" title="Project Explorer" type="button">
        <svg width="20" height="20" viewBox="0 0 20 20" fill="none"><rect x="3" y="3" width="6" height="14" rx="1.5" fill="currentColor" opacity=".5"/><rect x="11" y="3" width="6" height="6" rx="1.5" fill="currentColor"/><rect x="11" y="11" width="6" height="6" rx="1.5" fill="currentColor" opacity=".7"/></svg>
      </button>
      <button class="activity-btn" id="act-ai" title="AI Copilot" type="button">
        <svg width="20" height="20" viewBox="0 0 20 20" fill="none"><circle cx="10" cy="10" r="7" stroke="currentColor" stroke-width="1.5"/><path d="M7 10h6M10 7v6" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>
      </button>
      <div class="activity-spacer"></div>
      <button class="activity-btn devtools-btn" id="act-devtools" title="Developer Tools" type="button">
        <svg width="20" height="20" viewBox="0 0 20 20" fill="none"><path d="M6 7l-3 3 3 3M14 7l3 3-3 3M11 5l-2 10" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>
      </button>
    </nav>
    <aside class="panel left" id="panel-explorer">
      <div class="panel-title">Project Explorer</div>
      <div class="project-meta">
        <label>Name <input id="project-name" value="Untitled" /></label>
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
        </div>
      </div>
    </aside>
    <aside class="panel left ai-hidden" id="ai-panel">
      <div class="panel-title">AI Copilot</div>
      <div class="ai-mode">Manual path parity: every action has a no-AI equivalent.</div>
      <select id="ai-mode-select" title="Generation mode">
        <option value="scene">Scene (video)</option>
        <!-- Only video generation is wired today; audio/voice/dialogue come later. -->
      </select>
      <textarea id="ai-prompt" rows="4" placeholder="Describe a scene, shot list, or generation request..."></textarea>
      <div class="stack">
        <button class="btn" id="btn-health" type="button">Orchestrator Health</button>
        <button class="btn" id="btn-list-projects" type="button">List Projects</button>
        <button class="btn" id="btn-submit-job" type="button">Submit AI Job</button>
        <button class="btn" id="btn-refresh-job" type="button">Refresh Job</button>
        <div style="display:flex;gap:6px">
          <button class="btn btn-accept" id="btn-accept-job" type="button" disabled>Accept</button>
          <button class="btn btn-reject" id="btn-reject-job" type="button" disabled>Reject</button>
        </div>
      </div>
      <div id="ai-job-status" class="ai-job-status">No job submitted.</div>
      <div id="inspector" class="inspector">No clip selected.</div>
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
          <img id="preview-frame" alt="" />
          <video id="preview-video" playsinline></video>
          <div id="preview-empty" class="preview-overlay"><span>No clip at playhead</span></div>
        </div>
      </section>
      <section class="timeline">
        <div class="timeline-head">
          <h3>Timeline</h3>
          <div class="timeline-controls">
            <input id="playhead-slider" type="range" min="0" max="2400" value="288" />
            <button class="btn subtle" id="btn-add-video-track" type="button">+ Video Track</button>
            <button class="btn subtle" id="btn-add-audio-track" type="button">+ Audio Track</button>
            <button class="btn subtle" id="btn-split-clip" type="button">Split</button>
            <button class="btn subtle" id="btn-duplicate-clip" type="button">Duplicate</button>
            <button class="btn subtle" id="btn-delete-clip" type="button">Delete</button>
            <button class="btn subtle" id="btn-ripple-delete-clip" type="button" title="Delete and close the gap">Ripple</button>
          </div>
        </div>
        <div class="hint">Hotkeys: J/K/L shuttle, Arrow keys frame-step, M marker, S split, Ctrl+D duplicate, Del delete, Shift+Del ripple delete</div>
        <div id="timeline-grid" class="timeline-grid"></div>
      </section>
    </main>
  </div>
  <div class="devtools-drawer" id="devtools-drawer" style="display:none">
    <div class="devtools-header"><span>Developer Tools — Endpoint Log</span><button class="btn subtle" id="btn-close-devtools" type="button">Close</button></div>
    <pre id="out" class="devtools-out"></pre>
  </div>
  </div>
</div>
</div>

<!-- NEW PROJECT MODAL (hidden by default) -->
<div id="modal-overlay" class="modal-overlay" style="display:none">
  <div class="modal">
    <div class="modal-header">
      <h2>New Project</h2>
      <button class="modal-close" id="modal-close" type="button">&times;</button>
    </div>
    <p class="modal-sub">Choose a template to get started quickly, or start from a blank canvas.</p>
    <div class="template-grid" id="template-grid"></div>
  </div>
</div>

<!-- SAVE FAILURE (hidden by default). Deliberately has no × and no backdrop
     dismiss: leaving has to be an explicit choice between the two buttons. -->
<div id="save-error-overlay" class="modal-overlay" style="display:none">
  <div class="modal">
    <div class="modal-header">
      <h2>Couldn't save your timeline</h2>
    </div>
    <p class="modal-sub" id="save-error-stake"></p>
    <div class="modal-error" id="save-error-detail"></div>
    <div class="modal-actions">
      <button class="btn subtle" id="btn-leave-anyway" type="button">Leave anyway</button>
      <button class="btn" id="btn-return-to-project" type="button">Return to project</button>
    </div>
  </div>
</div>

<div id="toast-host"></div>
`;
  renderTemplateGrid();
}

// ── renderTemplateGrid: populate the template selection modal ──
function renderTemplateGrid(): void {
  const grid = document.getElementById("template-grid");
  if (!grid) return;
  grid.innerHTML = PROJECT_TEMPLATES.map(
    (t) => `
    <div class="template-card" data-template-id="${t.id}">
      <div class="template-name">${t.name}</div>
      <div class="template-desc">${t.description}</div>
      <div class="template-tracks">${t.tracks.map((tr) => `<span class="track-badge ${tr.kind.toLowerCase()}">${tr.name}</span>`).join("")}</div>
    </div>`,
  ).join("");
}

// ============================================================
// bootstrapStudioApp — entry point called from main.ts
// ============================================================
export function bootstrapStudioApp(): void {
  const app = document.querySelector<HTMLDivElement>("#app");
  if (!app) throw new Error("Missing #app root element");

  // ── State ──
  const state: StudioState = createInitialState();
  const history: HistoryStack = createHistoryStack();

  // Inject DOM and CSS
  buildStyle();
  buildDom(app);

  // ── Element references ──
  const $ = (sel: string) => document.querySelector<HTMLElement>(sel)!;
  const homeView = $("#home-view");
  const studioView = $("#studio-view");
  const modalOverlay = $("#modal-overlay");
  const devtoolsDrawer = $("#devtools-drawer");
  const devtoolsOut = $("#out") as HTMLPreElement;
  const actDevtools = $("#act-devtools");
  const actExplorer = $("#act-explorer");
  const actAi = $("#act-ai");
  const panelExplorer = $("#panel-explorer");
  const aiPanel = $("#ai-panel");
  const timecodeEl = $("#timecode");
  const sliderEl = $("#playhead-slider") as HTMLInputElement;
  const timelineGrid = $("#timeline-grid");
  const assetList = $("#asset-list");
  const inspectorEl = $("#inspector");
  const zoomSlider = $("#timeline-zoom") as HTMLInputElement;
  const fpsInput = $("#project-fps") as HTMLInputElement;
  const aiPrompt = $("#ai-prompt") as HTMLTextAreaElement;
  const homePrompt = $("#home-prompt") as HTMLTextAreaElement;
  const homePromptStatus = $("#home-prompt-status");
  const generateBtn = $("#btn-home-generate") as HTMLButtonElement;
  const previewFrame = document.getElementById("preview-frame") as HTMLImageElement;
  const previewVideo = document.getElementById("preview-video") as HTMLVideoElement;
  const previewEmpty = $("#preview-empty");
  const aiModeSelect = $("#ai-mode-select") as HTMLSelectElement;
  const jobStatusEl = $("#ai-job-status") as HTMLElement;
  const acceptBtn = $("#btn-accept-job") as HTMLButtonElement;
  const rejectBtn = $("#btn-reject-job") as HTMLButtonElement;

  // ── Dev mode ──
  // No toggle in the UI: developers opt in with
  // localStorage.setItem("deepiri_dev_mode", "true") and reload.
  function applyDevMode(): void {
    const on = state.devMode;
    actDevtools.classList.toggle("dev-hidden", !on);
    if (!on && devtoolsDrawer.style.display !== "none") {
      devtoolsDrawer.style.display = "none";
      actDevtools.classList.remove("active");
    }
  }

  // ── Devtools log ──
  function devLog(msg: string): void {
    if (!state.devMode) return;
    devtoolsOut.textContent += `${new Date().toISOString().slice(11, 23)}  ${msg}\n`;
    devtoolsOut.scrollTop = devtoolsOut.scrollHeight;
  }

  // ── Toasts ──
  const toastHost = $("#toast-host");

  /** Transient message, bottom-right. Click to dismiss early. */
  function toast(message: string, kind: "ok" | "error" = "ok"): void {
    const el = document.createElement("div");
    el.className = `toast toast-${kind}`;
    el.textContent = message;
    const remove = () => el.remove();
    el.addEventListener("click", remove);
    toastHost.appendChild(el);
    // Errors linger: they usually need reading, and often acting on.
    window.setTimeout(remove, kind === "error" ? 8000 : 3000);
  }

  // -- Timeline Persistence --
  /** Returns null on success, or the error text so callers can surface it. */
  async function persistTimeline(): Promise<string | null> {
    const sid = state.activeSequenceId;
    if (!sid) return null;
    const clips = state.timeline.tracks.flatMap((t) =>
      t.serverId
        ? t.clips
            .filter((c) => c.assetId)
            .map((c) => ({
              id: c.clipId,
              track_id: t.serverId!,
              asset_id: c.assetId!,
              in_tick: c.inTick,
              out_tick: c.outTick,
            }))
        : [],
    );
    try {
      await orchestratorReplaceClips(sid, clips);
      devLog(`Saved ${clips.length} clip(s)`);
      return null;
    } catch (e) {
      devLog(`Save timeline error: ${String(e)}`);
      return String(e);
    }
  }

  /** How many clips a failed save would take with it — the stake, stated. */
  function unsavedClipCount(): number {
    return state.timeline.tracks.reduce(
      (n, t) => n + (t.serverId ? t.clips.filter((c) => c.assetId).length : 0),
      0,
    );
  }

  function showSaveFailedModal(error: string, onLeave: () => void): void {
    const overlay = $("#save-error-overlay");
    const n = unsavedClipCount();
    $("#save-error-stake").textContent =
      `${n} clip${n === 1 ? "" : "s"} ${n === 1 ? "has" : "have"} not been saved. ` +
      `Leaving now discards ${n === 1 ? "it" : "them"}.`;
    $("#save-error-detail").textContent = error;

    const close = () => (overlay.style.display = "none");
    ($("#btn-return-to-project") as HTMLButtonElement).onclick = close;
    ($("#btn-leave-anyway") as HTMLButtonElement).onclick = () => {
      devLog(`Left project with ${n} unsaved clip(s) discarded`);
      close();
      onLeave();
    };
    overlay.style.display = "";
  }

  // ── Navigation ──
  function navigateTo(view: "home" | "studio"): void {
    state.currentView = view;
    if (view === "home") {
      homeView.style.display = "";
      studioView.style.display = "none";
      state.activeProjectId = null;
      state.activeSequenceId = null;
      resetProjectView();
      refreshHomeProjects();
    } else {
      homeView.style.display = "none";
      studioView.style.display = "";
    }
  }

  /**
   * Saving has to finish before navigateTo runs
   */
  async function goHome(): Promise<void> {
    const err = await persistTimeline();
    if (err) {
      showSaveFailedModal(err, () => navigateTo("home"));
      return;
    }
    navigateTo("home");
  }

  /**
   * Puts the app back to "no project open". resetProjectState() clears the
   * plain data; everything below it releases a resource that state can't
   * clear on its own — running timers, the monitor element, the AI panel.
   */
  function resetProjectView(): void {
    resetProjectState(state, history);

    pause(state);
    stopProxyPolling(state);
    stopJobPolling();
    setReviewButtons(false);
    jobStatusEl.textContent = "";
    const playBtn = $("#btn-play");
    if (playBtn) playBtn.textContent = "Play";

    previewVideo.pause();
    previewVideo.removeAttribute("src");
    previewVideo.load();
    previewVideo.style.display = "none";
    previewFrame.removeAttribute("src");
    previewFrame.style.display = "none";
    previewEmpty.style.display = "";
  }

  // ── Home project list ──
  let cachedProjects: Project[] = [];
  async function refreshHomeProjects(): Promise<void> {
    const listEl = $("#home-project-list");
    const countEl = $("#home-project-count");
    const loadingEl = $("#home-loading");
    const errorEl = $("#home-error");
    try {
      const res = await orchestratorListProjects();
      cachedProjects = res.items;
    } catch {
      cachedProjects = [];
    }
    const homeCbs: HomeCallbacks = {
      onOpenProject: openProject,
      onNewProject: () => {
        modalOverlay.style.display = "";
      },
      onRefresh: refreshHomeProjects,
      onDeleteProject: async (id) => {
        cachedProjects = cachedProjects.filter((p) => p.id !== id);
        await refreshHomeProjects();
      },
    };
    await renderHomeProjects(
      cachedProjects,
      listEl,
      countEl,
      loadingEl,
      errorEl,
      homeCbs,
    );
  }

  // ── Open a project → create default sequence if needed ──
  async function openProject(project: Project): Promise<void> {
    const pid = project.id;
    resetProjectView();
    state.activeProjectId = pid;
    state.timeline.fps = project.fps_num / project.fps_den;
    fpsInput.value = String(state.timeline.fps);
    try {
      const seqs = await orchestratorListSequences(pid);
      if (seqs.length > 0) {
        state.activeSequenceId = seqs[0].id;
      } else {
        const seq = await orchestratorCreateSequence(pid, "Main Sequence");
        state.activeSequenceId = seq.id;
      }
    } catch {
      const seq = await orchestratorCreateSequence(pid, "Main Sequence");
      state.activeSequenceId = seq.id;
    }
    // Load assets
    try {
      const assets = await listProjectAssets(pid);
      if (state.activeProjectId !== pid) return;
      for (const a of assets) registerAsset(state, a);
      startProxyPolling(state, getAsset, (updated) => {
        updateAsset(state, updated.id, updated);
        renderAssets();
      });
    } catch {
      /* no assets yet — the bin stays empty from the reset */
    }

    // Load this project's tracks and clips. The timeline is empty after the
    // reset, so a failure here leaves it empty rather than showing the last
    // project's.
    try {
      const rows = await orchestratorListTracks(state.activeSequenceId);
      if (state.activeProjectId !== pid) return;
      const tracks = rows
        .slice()
        // The timeline only draws video and audio lanes; anything else the
        // server holds would otherwise render as a bogus video track.
        .filter((t) => t.track_type === "video" || t.track_type === "audio")
        .sort((a, b) => a.lane_index - b.lane_index)
        .map((t, i): import("./types").UiTrack => ({
          id: i + 1,
          serverId: t.id,
          name: t.name,
          kind: t.track_type === "audio" ? "Audio" : "Video",
          lane_index: t.lane_index,
          clips: [],
        }));

      const clipRows = await orchestratorListClips(state.activeSequenceId);
      if (state.activeProjectId !== pid) return;
      const byTrack = new Map(tracks.map((t) => [t.serverId, t]));
      // In tick order: insertClipFromAsset appends after the last clip, so an
      // unsorted list would put the next insert in the wrong place.
      for (const c of clipRows.slice().sort((a, b) => a.in_tick - b.in_tick)) {
        const track = byTrack.get(c.track_id);
        if (!track) continue;
        const asset = state.assets.find((a) => a.id === c.asset_id);
        track.clips.push({
          id: state.nextClipId++,
          clipId: c.id,
          assetId: c.asset_id,
          label: asset?.uri.split("/").pop() ?? c.asset_id,
          inTick: c.in_tick,
          outTick: c.out_tick,
          color: "#4d7dff",
        });
      }

      state.timeline.tracks = tracks;
      state.ui.activeTrackId = tracks[0]?.id ?? null;
      const maxOut = Math.max(0, ...tracks.flatMap((t) => t.clips.map((c) => c.outTick)));
      if (maxOut + state.timeline.fps * 2 > state.timeline.durationTicks) {
        state.timeline.durationTicks = maxOut + state.timeline.fps * 2;
      }
    } catch (e) {
      devLog(`Load timeline error: ${String(e)}`);
    }
    navigateTo("studio");
    renderTimelineFull();
    renderAssets();
    updateInspector(state, inspectorEl);
  }

  // ── Home prompt → generated video in the editor ──
  /**
   * The ChatGPT-shaped path: one prompt creates the project, starts the
   * generation, and drops the user straight into the editor to watch it land.
   */
  async function generateFromPrompt(prompt: string): Promise<void> {
    if (!prompt.trim()) {
      homePromptStatus.textContent = "Describe the video you want first.";
      homePromptStatus.classList.add("error");
      return;
    }
    generateBtn.disabled = true;
    homePromptStatus.classList.remove("error");
    homePromptStatus.textContent = "Setting up your project…";
    try {
      const launched = await launchAiProject(prompt, {
        createProject: orchestratorCreateProject,
        createSequence: orchestratorCreateSequence,
        createTrack: orchestratorCreateTrack,
        submitAiJob,
      });
      devLog(`Prompt launch: project ${launched.project.id}, job ${launched.jobId}`);
      homePrompt.value = "";
      homePromptStatus.textContent = "";

      // Into the editor, AI panel open, with the clip auto-accepted on arrival.
      await openProject(launched.project);
      state.lastJobId = launched.jobId;
      aiPrompt.value = prompt.trim();
      setActivePanel("ai");
      jobStatusEl.textContent = "Status: queued\nGenerating your video…";
      startJobPolling(launched.jobId, true);
    } catch (e) {
      homePromptStatus.textContent = `Could not start generation: ${String(e)}`;
      homePromptStatus.classList.add("error");
      devLog(`Prompt launch error: ${String(e)}`);
    } finally {
      generateBtn.disabled = false;
    }
  }

  // ── Create project from template ──
  async function createProjectFromTemplate(
    template: ProjectTemplate,
  ): Promise<void> {
    modalOverlay.style.display = "none";
    devLog(`Creating project from template: ${template.name}`);
    try {
      const proj = await orchestratorCreateProject(template.name);
      const seq = await orchestratorCreateSequence(proj.id, "Main Sequence");
      for (const t of template.tracks) {
        await orchestratorCreateTrack(
          seq.id,
          t.kind.toLowerCase(),
          t.lane_index,
          t.name,
        );
      }
      devLog(`Project created: ${proj.id} / sequence: ${seq.id}`);
      await refreshHomeProjects();
      await openProject(proj);
    } catch (err) {
      devLog(`Create project error: ${String(err)}`);
    }
  }

  // ── Timeline rendering wrapper ──
  const timelineCbs: TimelineCallbacks = {
    onTrackNameClick: (trackId) => {
      state.ui.activeTrackId =
        state.ui.activeTrackId === trackId ? null : trackId;
      renderTimelineFull();
    },
    onTrackDelete: (trackId) => {
      const idx = state.timeline.tracks.findIndex((t) => t.id === trackId);
      if (idx < 0) return;
      const track = state.timeline.tracks[idx];
      if (track.clips.length > 0) {
        if (!window.confirm(`Delete "${track.name}"? This will also remove ${track.clips.length} clip(s).`)) return;
      }
      state.timeline.tracks.splice(idx, 1);
      // Tracks are server-backed now, so a local-only splice would come back on
      // the next open. The clips cascade with it server-side.
      if (track.serverId && state.activeSequenceId) {
        void orchestratorDeleteTrack(state.activeSequenceId, track.serverId).catch(
          (e) => devLog(`Delete track error: ${String(e)}`),
        );
      }
      if (state.ui.activeTrackId === trackId) {
        state.ui.activeTrackId = state.timeline.tracks[0]?.id ?? null;
      }
      if (state.ui.selectedClipId != null) {
        const exists = state.timeline.tracks.some((t) => t.clips.some((c) => c.id === state.ui.selectedClipId));
        if (!exists) state.ui.selectedClipId = null;
      }
      renderTimelineFull();
      updateInspector(state, inspectorEl);
    },
    onLaneClick: (trackId, tick) => {
      state.ui.activeTrackId = trackId;
      seek(state, tick);
      renderTimelineFull();
      void fetchFrameForPlayhead();
    },
    onClipClick: (clipId, trackId) => {
      state.ui.selectedClipId =
        state.ui.selectedClipId === clipId ? null : clipId;
      state.ui.activeTrackId = trackId;
      renderTimelineFull();
      updateInspector(state, inspectorEl);
    },
    onClipPointerDown: (
      clipId,
      _trackId,
      mode,
      event,
      laneRect,
      scaledDuration,
    ) => {
      handleClipDrag(clipId, mode, event, laneRect, scaledDuration);
    },
  };

  function renderTimelineFull(): void {
    sliderEl.max = String(state.timeline.durationTicks);
    renderTimeline(state, timelineGrid, timecodeEl, sliderEl, timelineCbs);
  }

  // Stream an asset straight into the program monitor (single-click preview).
  // Uses the ready proxy (for AI clips that's the generated mp4 itself); if no
  // proxy is available yet there's nothing web-playable to show.
  function previewAssetInMonitor(asset: Asset): void {
    const meta = asset.meta_jsonb ?? {};
    const src = meta.proxy_status === "ready" && meta.proxy_path
      ? String(meta.proxy_path)
      : null;
    if (!src) {
      devLog(`No playable proxy for "${meta.name ?? asset.uri}" (proxy_status=${meta.proxy_status ?? "unavailable"})`);
      return;
    }
    playClipInMonitor(src);
  }

  function renderAssets(): void {
    renderAssetList(state.assets, assetList, {
      onAssetPreview: (asset) => previewAssetInMonitor(asset),
    });
  }

  async function refreshAssets(): Promise<void> {
    const pid = state.activeProjectId;
    if (!pid) return;
    try {
      const assets = await listProjectAssets(pid);
      // The user may have switched projects while this was in flight.
      if (state.activeProjectId !== pid) return;
      state.assets = [];
      for (const a of assets) registerAsset(state, a);
      renderAssets();
    } catch {
      /* leave existing assets in place on failure */
    }
  }

  // ── Clip drag logic ──
  function handleClipDrag(
    clipId: number,
    mode: "move" | "trim-left" | "trim-right",
    startEvent: PointerEvent,
    laneRect: DOMRect,
    scaledDuration: number,
  ): void {
    const startX = startEvent.clientX;
    const startInTick = (() => {
      const found = getClipById(state, clipId);
      return found ? found.clip.inTick : 0;
    })();
    const startOutTick = (() => {
      const found = getClipById(state, clipId);
      return found ? found.clip.outTick : 0;
    })();
    const tickPerPx = scaledDuration / laneRect.width / state.ui.zoom;
    // ~8px of slack, so snapping feels the same at any zoom level.
    const snapThreshold = Math.max(1, Math.round(8 * tickPerPx));
    const onMove = (e: PointerEvent) => {
      const dx = e.clientX - startX;
      const deltaTick = Math.round(dx * tickPerPx);
      if (mode === "move") {
        // Positioned against the drag's origin, not the clip's current spot —
        // offsetting from the live position compounds every pointer event.
        const targetIn = snapTick(
          state,
          startInTick + deltaTick,
          clipId,
          snapThreshold,
        );
        const found = getClipById(state, clipId);
        if (found) {
          moveClip(state, clipId, targetIn - found.clip.inTick, history);
        }
      } else if (mode === "trim-left") {
        const snapped = snapTick(state, startInTick + deltaTick, clipId, snapThreshold);
        const newIn = Math.min(snapped, startOutTick - 2);
        const found = getClipById(state, clipId);
        if (found) {
          found.clip.inTick = Math.max(0, newIn);
        }
      } else {
        const snapped = snapTick(state, startOutTick + deltaTick, clipId, snapThreshold);
        const newOut = Math.max(snapped, startInTick + 2);
        const found = getClipById(state, clipId);
        if (found) {
          found.clip.outTick = Math.min(state.timeline.durationTicks, newOut);
        }
      }
      renderTimelineFull();
    };
    const onUp = () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      commitHistory(
        state,
        history,
        mode === "move" ? "move clip" : "trim clip",
      );
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
  }

  // ── Preview ──
  let wasPlayingBeforeScrub = false;

  function clipAtPlayhead() {
    const ph = state.timeline.playheadTick;
    for (const track of state.timeline.tracks) {
      if (track.kind !== "Video") continue;
      for (const clip of track.clips) {
        if (clip.inTick <= ph && ph < clip.outTick && clip.assetId) {
          const asset = state.assets.find((a) => a.id === clip.assetId) ?? null;
          if (asset) return { clip, asset };
        }
      }
    }
    return null;
  }

  async function fetchFrameForPlayhead(): Promise<void> {
    const pid = state.activeProjectId;
    const found = clipAtPlayhead();
    if (!found) {
      previewFrame.style.display = "none";
      previewVideo.style.display = "none";
      previewEmpty.style.display = "";
      return;
    }
    const { clip, asset } = found;
    const offsetSecs = (state.timeline.playheadTick - clip.inTick) / state.timeline.fps;
    
    const proxyPath = asset.meta_jsonb?.proxy_path;
    if (!proxyPath) {
      previewFrame.style.display = "none";
      previewEmpty.style.display = "";
      return;
    }
    previewEmpty.style.display = "none";
    try {
      const b64 = await fetchFrame(proxyPath, offsetSecs);
      // Don't paint a frame the user has already navigated away from.
      if (state.activeProjectId !== pid) return;
      previewFrame.src = `data:image/jpeg;base64,${b64}`;
      previewFrame.style.display = "block";
    } catch {
      previewFrame.style.display = "none";
      previewEmpty.style.display = "";
    }
  }

  function startProxyPlayback(): void {
    const found = clipAtPlayhead();
    if (!found) return;
    const { clip, asset } = found;
    const proxyPath = asset.meta_jsonb?.proxy_path;
    if (asset.meta_jsonb?.proxy_status !== "ready" || !proxyPath) return;
    const offsetSecs = (state.timeline.playheadTick - clip.inTick) / state.timeline.fps;
    previewVideo.src = getStreamUrl(proxyPath);
    previewVideo.currentTime = offsetSecs;
    previewVideo.play().catch(() => {});
    previewVideo.style.display = "block";
    previewFrame.style.display = "none";
    previewEmpty.style.display = "none";
  }

  function stopProxyPlayback(): void {
    previewVideo.pause();
    previewVideo.style.display = "none";
    void fetchFrameForPlayhead();
  }

  function playClipInMonitor(path: string): void {
    previewVideo.src = getStreamUrl(path);
    previewVideo.currentTime = 0;
    previewVideo.play().catch(() => {});
    previewVideo.style.display = "block";
    previewFrame.style.display = "none";
    previewEmpty.style.display = "none";
  }

  // ── Transport ──
  function jogLeft() {
    jog(state, -1);
    renderTimelineFull();
    void fetchFrameForPlayhead();
  }
  function jogRight() {
    jog(state, 1);
    renderTimelineFull();
    void fetchFrameForPlayhead();
  }
  function togglePlay() {
    if (state.playing) {
      pause(state);
      stopProxyPlayback();
    } else {
      play(state, () => {
        seek(state, state.timeline.playheadTick + 1);
        renderTimelineFull();
      });
      startProxyPlayback();
    }
    const playBtn = $("#btn-play");
    if (playBtn) playBtn.textContent = state.playing ? "Pause" : "Play";
    renderTimelineFull();
  }
  function shuttleBack() {
    shuttle(state, -2, () => {
      jog(state, -1);
      renderTimelineFull();
    });
  }
  function shuttleStop() {
    stop(state);
    stopProxyPlayback();
    const playBtn = $("#btn-play");
    if (playBtn) playBtn.textContent = "Play";
    renderTimelineFull();
  }
  function shuttleForward() {
    shuttle(state, 2, () => {
      jog(state, 1);
      renderTimelineFull();
    });
  }

  // ── Split / Delete ──
  function doSplitClip() {
    splitClip(state, history);
    renderTimelineFull();
    updateInspector(state, inspectorEl);
  }
  function doDeleteClip() {
    deleteClip(state, history);
    renderTimelineFull();
    updateInspector(state, inspectorEl);
  }
  function doRippleDeleteClip() {
    rippleDeleteClip(state, history);
    renderTimelineFull();
    updateInspector(state, inspectorEl);
  }
  function doDuplicateClip() {
    duplicateClip(state, history);
    renderTimelineFull();
    updateInspector(state, inspectorEl);
  }

  // ── Undo / Redo ──
  function doUndo() {
    undoHistory(state, history);
    renderTimelineFull();
    updateInspector(state, inspectorEl);
  }
  function doRedo() {
    redoHistory(state, history);
    renderTimelineFull();
    updateInspector(state, inspectorEl);
  }

  // ── Markers ──
  function doAddMarker() {
    addMarker(state, history);
    renderTimelineFull();
  }
  function doJumpNextMarker() {
    jumpToNextMarker(state);
    renderTimelineFull();
  }

  // ── AI actions ──
  async function doHealth() {
    try {
      const r = await orchestratorHealth();
      devLog(`Health: ${JSON.stringify(r)}`);
    } catch (e) {
      devLog(`Health error: ${String(e)}`);
    }
  }
  async function doListProjects() {
    await goHome();
  }
  // ── AI job progress (Task 12): poll status, show stages, gate review buttons ──
  let jobPollTimer: number | null = null;
  // States the worker won't move on from on its own (review/failed) plus the
  // post-review user states — polling stops here.
  const JOB_TERMINAL = new Set(["review", "failed", "committed", "accepted", "rejected"]);

  function setReviewButtons(enabled: boolean): void {
    acceptBtn.disabled = !enabled;
    rejectBtn.disabled = !enabled;
  }

  function renderJobStatus(job: AIJob): void {
    const stages = (job.stages || []).join(" → ");
    let line = `Status: ${job.status}`;
    if (stages) line += `\nStages: ${stages}`;
    if (job.status === "failed") {
      const err = job.metadata?.error || job.metadata?.artifact_error;
      if (err) line += `\nError: ${String(err)}`;
    }
    jobStatusEl.textContent = line;
    // Accept/Reject are only meaningful while the job awaits review.
    setReviewButtons(job.status === "review");
  }

  function stopJobPolling(): void {
    if (jobPollTimer !== null) {
      clearInterval(jobPollTimer);
      jobPollTimer = null;
    }
  }

  /**
   * Polls a job to completion.
   *
   * `autoAccept` is for the home-page prompt flow: the user asked for a video
   * and expects one, so we take the clip as soon as it is ready instead of
   * parking it behind a review gate. The AI panel's own Submit keeps the
   * explicit Accept/Reject step.
   */
  function startJobPolling(jobId: string, autoAccept = false): void {
    stopJobPolling();
    jobPollTimer = window.setInterval(async () => {
      try {
        const job = await getAiJob(jobId);
        renderJobStatus(job);
        if (JOB_TERMINAL.has(job.status)) {
          stopJobPolling();
          devLog(`Job ${jobId} reached ${job.status}`);
          if (autoAccept && job.status === "review") await doAcceptJob();
        }
      } catch (e) {
        stopJobPolling();
        devLog(`Poll error: ${String(e)}`);
      }
    }, 800);
  }

  async function doSubmitJob() {
    if (!state.activeProjectId || !aiPrompt.value.trim()) return;
    stopJobPolling();
    setReviewButtons(false);
    jobStatusEl.textContent = "Submitting…";
    try {
      const res = await submitAiJob(
        state.activeProjectId,
        aiPrompt.value.trim(),
        aiModeSelect.value,
      );
      devLog(`AI job submitted: ${res.job_id} (mode=${aiModeSelect.value})`);
      state.lastJobId = res.job_id;
      jobStatusEl.textContent = `Status: ${res.status}`;
      startJobPolling(res.job_id);
    } catch (e) {
      jobStatusEl.textContent = `Submit failed: ${String(e)}`;
      devLog(`Submit job error: ${String(e)}`);
    }
  }
  async function doRefreshJob() {
    if (!state.lastJobId) return;
    try {
      const job = await getAiJob(state.lastJobId);
      renderJobStatus(job);
      devLog(`Job ${job.id}: ${job.status} stages=[${(job.stages || []).join(",")}]`);
    } catch (e) {
      devLog(`Refresh job error: ${String(e)}`);
    }
  }
  async function doAcceptJob() {
    if (!state.lastJobId) return;
    try {
      const job = await acceptAiJob(state.lastJobId);
      stopJobPolling();
      setReviewButtons(false);
      jobStatusEl.textContent = `Status: ${job.status}`;
      devLog(`Job ${state.lastJobId} accepted`);
      const outputPath = job.metadata?.output_path;
      if (outputPath) {
        playClipInMonitor(outputPath);
        devLog(`Playing accepted clip in monitor`);
      }
      // Surface the new AI asset in the library so the user can click/drag it
      // onto the timeline later (it plays there now that its proxy is ready).
      await refreshAssets();

      // Cut the generated clip straight into the timeline. It also lands on
      // the server's sequence, which is what Export renders from.
      try {
        const clip = await insertAcceptedClip(state, history, job, {
          getAsset,
          listTracks: orchestratorListTracks,
          createTrack: orchestratorCreateTrack,
          createClip: orchestratorCreateClip,
        });
        if (clip) {
          jobStatusEl.textContent = `Status: ${job.status}\nAdded "${clip.label}" to the timeline.`;
          devLog(`Inserted accepted clip ${clip.label} at tick ${clip.inTick}`);
        } else {
          // null has two causes — name the right one instead of always
          // blaming a missing asset the job may well have produced.
          const why = job.metadata?.asset_id
            ? "this project has no video track to hold it"
            : "the job produced no asset";
          jobStatusEl.textContent = `Status: ${job.status}\nNo clip added — ${why}.`;
          devLog(`Accepted job ${state.lastJobId}: no clip added — ${why}`);
        }
      } catch (e) {
        // ServerSyncError means the clip is on the local timeline but its
        // server-side copy is missing — devLog alone would hide that in
        // production, and Export renders from the server's clip list, so
        // the exported file would silently skip the clip. Say it in the UI.
        const synced = e instanceof ServerSyncError ? e.clip : null;
        jobStatusEl.textContent = synced
          ? `Status: ${job.status}\nAdded "${synced.label}" to the timeline, but it wasn't saved on the server — Export will skip it. (${String(e)})`
          : `Status: ${job.status}\nCouldn't add the clip to the timeline: ${String(e)}`;
        devLog(`Clip insert problem: ${String(e)}`);
      }
      renderTimelineFull();
      updateInspector(state, inspectorEl);
    } catch (e) {
      jobStatusEl.textContent = `Accept failed: ${String(e)}`;
      devLog(`Accept error: ${String(e)}`);
    }
  }
  async function doRejectJob() {
    if (!state.lastJobId) return;
    try {
      await rejectAIJob(state.lastJobId);
      stopJobPolling();
      setReviewButtons(false);
      jobStatusEl.textContent = "Status: rejected";
      devLog(`Job ${state.lastJobId} rejected`);
    } catch (e) {
      devLog(`Reject error: ${String(e)}`);
    }
  }

  // ── Hotkeys ──
  const hotkeyDispatch: HotkeyDispatch = {
    jogBack: jogLeft,
    jogForward: jogRight,
    shuttleBack,
    shuttleStop,
    shuttleForward,
    addMarker: doAddMarker,
    splitClip: doSplitClip,
    deleteClip: doDeleteClip,
    rippleDeleteClip: doRippleDeleteClip,
    duplicateClip: doDuplicateClip,
    undo: doUndo,
    redo: doRedo,
  };
  const unregisterHotkeys = registerHotkeys(hotkeyDispatch);

  // ── Panel toggle ──
  let activePanel: "explorer" | "ai" = "explorer";
  function setActivePanel(panel: "explorer" | "ai"): void {
    activePanel = panel;
    actExplorer.classList.toggle("active", panel === "explorer");
    actAi.classList.toggle("active", panel === "ai");
    panelExplorer.classList.toggle("ai-hidden", panel !== "explorer");
    aiPanel.classList.toggle("ai-hidden", panel !== "ai");
  }

  // ── Devtools toggle ──
  function toggleDevtools(): void {
    if (!state.devMode) return;
    const open = devtoolsDrawer.style.display !== "none";
    if (open) {
      devtoolsDrawer.style.display = "none";
      actDevtools.classList.remove("active");
    } else {
      devtoolsDrawer.style.display = "";
      actDevtools.classList.add("active");
    }
  }

  // ═══════════════════════════════════════════
  // Event wiring
  // ═══════════════════════════════════════════

  // Navigation
  $("#brand-studio").addEventListener("click", () => void goHome());
  $("#btn-home-nav").addEventListener("click", () => void goHome());
  $("#btn-list-projects").addEventListener("click", doListProjects);

  // Dev mode
  actDevtools.addEventListener("click", toggleDevtools);
  $("#btn-close-devtools").addEventListener("click", () => {
    devtoolsDrawer.style.display = "none";
    actDevtools.classList.remove("active");
  });

  // Panel toggles
  actExplorer.addEventListener("click", () => setActivePanel("explorer"));
  actAi.addEventListener("click", () => setActivePanel("ai"));

  // Home buttons
  $("#btn-home-new-project").addEventListener("click", () => {
    modalOverlay.style.display = "";
  });
  $("#btn-home-refresh").addEventListener("click", refreshHomeProjects);
  $("#btn-home-retry").addEventListener("click", refreshHomeProjects);

  // Prompt entry: Generate, Enter-to-send, and one-click starter prompts.
  generateBtn.addEventListener("click", () => generateFromPrompt(homePrompt.value));
  homePrompt.addEventListener("keydown", (e) => {
    const ev = e as KeyboardEvent;
    if (ev.key === "Enter" && !ev.shiftKey) {
      ev.preventDefault();
      void generateFromPrompt(homePrompt.value);
    }
  });
  $("#home-suggestions").addEventListener("click", (e) => {
    const chip = (e.target as HTMLElement).closest<HTMLElement>(".suggestion-chip");
    if (!chip) return;
    const prompt = chip.dataset.prompt ?? "";
    homePrompt.value = prompt;
    void generateFromPrompt(prompt);
  });

  // Modal
  $("#modal-close").addEventListener("click", () => {
    modalOverlay.style.display = "none";
  });
  modalOverlay.addEventListener("click", (e) => {
    if (e.target === modalOverlay) modalOverlay.style.display = "none";
  });
  document.getElementById("template-grid")!.addEventListener("click", (e) => {
    const card = (e.target as HTMLElement).closest<HTMLElement>(
      ".template-card",
    );
    if (!card) return;
    const id = card.dataset.templateId!;
    const tpl = PROJECT_TEMPLATES.find((t) => t.id === id);
    if (tpl) createProjectFromTemplate(tpl);
  });

  // Transport
  $("#btn-back").addEventListener("click", jogLeft);
  $("#btn-play").addEventListener("click", togglePlay);
  $("#btn-forward").addEventListener("click", jogRight);

  // Timeline controls
  $("#btn-add-marker").addEventListener("click", doAddMarker);
  $("#btn-jump-next-marker").addEventListener("click", doJumpNextMarker);
  $("#btn-split-clip").addEventListener("click", doSplitClip);
  $("#btn-duplicate-clip").addEventListener("click", doDuplicateClip);
  $("#btn-delete-clip").addEventListener("click", doDeleteClip);
  $("#btn-ripple-delete-clip").addEventListener("click", doRippleDeleteClip);
  $("#btn-undo").addEventListener("click", doUndo);
  $("#btn-redo").addEventListener("click", doRedo);

  // Zoom
  zoomSlider.addEventListener("input", () => {
    state.ui.zoom = parseFloat(zoomSlider.value);
    renderTimelineFull();
  });

  // FPS
  fpsInput.addEventListener("change", () => {
    const v = parseInt(fpsInput.value, 10);
    if (v > 0) {
      state.timeline.fps = v;
      renderTimelineFull();
    }
  });

  // Playhead slider
  sliderEl.addEventListener("pointerdown", () => {
    if (state.playing) {
      togglePlay(); // pauses since state.playing is true
      wasPlayingBeforeScrub = true;
    }
  });
  sliderEl.addEventListener("input", () => {
    seek(state, parseInt(sliderEl.value, 10));
    renderTimelineFull();
    void fetchFrameForPlayhead();
  });
  sliderEl.addEventListener("pointerup", () => {
    if (wasPlayingBeforeScrub) {
      wasPlayingBeforeScrub = false;
      togglePlay(); // resumes since state.playing is false
    }
  });

  // AI panel buttons
  $("#btn-health").addEventListener("click", doHealth);
  $("#btn-submit-job").addEventListener("click", doSubmitJob);
  $("#btn-refresh-job").addEventListener("click", doRefreshJob);
  $("#btn-accept-job").addEventListener("click", doAcceptJob);
  $("#btn-reject-job").addEventListener("click", doRejectJob);

  // Import media
  $("#btn-import-media").addEventListener("click", async () => {
    if (!state.activeProjectId) return;
    const path = prompt("Enter file path to import:");
    if (!path) return;
    try {
      const asset = await importMedia(state.activeProjectId, path);
      registerAsset(state, asset);
      if (insertAssetIntoVideoTrack(state, asset, history)) renderTimelineFull();
      renderAssets();
      // Start proxy polling if needed
      if (asset.meta_jsonb?.proxy_status === "pending") {
        startProxyPolling(state, getAsset, (updated) => {
          updateAsset(state, updated.id, updated);
          renderAssets();
          void fetchFrameForPlayhead();
        });
      }
      void fetchFrameForPlayhead();
      devLog(`Imported: ${asset.uri}`);
    } catch (e) {
      devLog(`Import error: ${String(e)}`);
    }
  });

  // Drag-and-drop import
  const dropZone = $("#drop-zone");
  dropZone.addEventListener("dragover", (e) => {
    e.preventDefault();
    dropZone.classList.add("drag-over");
  });
  dropZone.addEventListener("dragleave", () =>
    dropZone.classList.remove("drag-over"),
  );
  dropZone.addEventListener("drop", async (e) => {
    e.preventDefault();
    dropZone.classList.remove("drag-over");
    if (!state.activeProjectId) return;
    const files = e.dataTransfer?.files;
    if (!files?.length) return;
    for (const file of Array.from(files)) {
      try {
        const filePath = (file as File & { path?: string }).path || file.name;
        const asset = await importMedia(state.activeProjectId, filePath);
        registerAsset(state, asset);
        insertAssetIntoVideoTrack(state, asset, history);
        if (asset.meta_jsonb?.proxy_status === "pending") {
          startProxyPolling(state, getAsset, (updated) => {
            updateAsset(state, updated.id, updated);
            renderAssets();
            void fetchFrameForPlayhead();
          });
        }
      } catch (err) {
        devLog(`Drop import error: ${String(err)}`);
      }
    }
    renderTimelineFull();
    renderAssets();
    void fetchFrameForPlayhead();
  });

  // ── Add tracks ──
  //
  // Creates the track on the server first, exactly like Import Media creates
  // the asset first, then mirrors the returned row into the timeline. A track
  // without a serverId is invisible to persistTimeline() — it filters those
  // out — so a local-only track silently swallowed every clip placed on it.
  async function addTrack(kind: "Video" | "Audio"): Promise<void> {
    const sid = state.activeSequenceId;
    if (!sid) {
      devLog("Add track: open a project first.");
      return;
    }
    const prefix = kind === "Video" ? "V" : "A";
    const name = `${prefix}${
      state.timeline.tracks.filter((t) => t.kind === kind).length + 1
    }`;
    // Derive both indices from what's on screen. A module-level counter drifts
    // once you switch projects, since the timeline is rebuilt from the server.
    const laneIndex =
      state.timeline.tracks.reduce((m, t) => Math.max(m, t.lane_index), -1) + 1;
    const localId =
      state.timeline.tracks.reduce((m, t) => Math.max(m, t.id), 0) + 1;

    try {
      const row = await orchestratorCreateTrack(sid, kind.toLowerCase(), laneIndex, name);
      // The user may have switched projects while the request was in flight.
      if (state.activeSequenceId !== sid) return;
      state.timeline.tracks.push({
        id: localId,
        serverId: row.id,
        name: row.name,
        kind,
        lane_index: row.lane_index,
        clips: [],
      });
      state.ui.activeTrackId = localId;
      commitHistory(state, history, `add ${kind.toLowerCase()} track`);
      renderTimelineFull();
      devLog(`Track created: ${row.name} (${row.id})`);
    } catch (e) {
      devLog(`Add track error: ${String(e)}`);
    }
  }

  $("#btn-add-video-track").addEventListener("click", () => void addTrack("Video"));
  $("#btn-add-audio-track").addEventListener("click", () => void addTrack("Audio"));

  // Save / Export (placeholder)
  $("#btn-save-project").addEventListener("click", async () => {
    commitHistory(state, history, "save");
    const projectName = ($("#project-name") as HTMLInputElement).value || "Untitled";
    saveProject(projectName, snapshotState(state));
    const err = await persistTimeline();
    if (err) {
      toast(`Couldn't save timeline: ${err}`, "error");
      return;
    }
    devLog(`Project "${projectName}" saved.`);
    toast(`Project "${projectName}" saved`, "ok");
  });
  const exportBtn = $("#btn-export") as HTMLButtonElement;
  const exportStatusEl = $("#export-status") as HTMLElement;
  exportBtn.addEventListener("click", async () => {
    if (!state.activeProjectId || !state.activeSequenceId) {
      exportStatusEl.textContent = "Open a project first";
      return;
    }
    exportBtn.disabled = true;
    exportStatusEl.textContent = "Exporting…";
    try {
      const job = await runExport(
        state.activeProjectId,
        state.activeSequenceId,
        { submitRenderJob, getRenderJob },
        {
          onProgress: (j) => {
            exportStatusEl.textContent =
              j.status === "rendering"
                ? `Exporting… ${Math.round(j.progress * 100)}%`
                : `Export ${j.status}`;
          },
        },
      );
      if (job.status === "completed" && job.output_uri) {
        exportStatusEl.textContent = `Exported → ${job.output_uri}`;
        devLog(`Export completed: ${job.output_uri}`);
      } else {
        exportStatusEl.textContent = `Export failed: ${job.error ?? "unknown error"}`;
        devLog(`Export failed: ${job.error ?? "unknown error"}`);
      }
    } catch (e) {
      exportStatusEl.textContent = `Export failed: ${String(e)}`;
      devLog(`Export error: ${String(e)}`);
    } finally {
      exportBtn.disabled = false;
    }
  });

  // Theme toggle (placeholder)
  const toggleTheme = () => devLog("Theme toggle: not yet wired.");
  $("#btn-toggle-theme").addEventListener("click", toggleTheme);
  $("#btn-toggle-theme-home").addEventListener("click", toggleTheme);

  // ═══════════════════════════════════════════
  // Initialization
  // ═══════════════════════════════════════════

  applyDevMode();
  setActivePanel("explorer");
  refreshHomeProjects();
  renderTimelineFull();
  renderAssets();
  updateInspector(state, inspectorEl);

  // ── Cleanup on page unload ──
  window.addEventListener("beforeunload", () => {
    unregisterHotkeys();
    stopProxyPolling(state);
  });

  devLog("Studio bootstrapped.");
}
