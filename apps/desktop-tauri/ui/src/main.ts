import { invoke } from "@tauri-apps/api/core";

const app = document.querySelector<HTMLDivElement>("#app")!;

app.innerHTML = `
  <div class="studio">
    <header class="bar">Deepiri Renderflow Studio</header>
    <div class="grid">
      <aside class="pane left"><h3>Assets</h3><ul id="assets"></ul><button id="btn-probe" type="button">Probe media (path in console)</button></aside>
      <main class="pane center"><h3>Program</h3><div id="preview">Vulkan preview binds here</div></main>
      <aside class="pane right"><h3>AI Copilot</h3>
        <button id="btn-health" type="button">Orchestrator health</button>
        <button id="btn-projects" type="button">List projects (native)</button>
        <button id="btn-vulkan" type="button">Vulkan GPUs (native)</button>
        <button id="btn-timeline" type="button">Timeline resolve (native)</button>
        <pre id="out"></pre></aside>
    </div>
    <footer class="timeline"><h3>Timeline</h3><div id="tl">Tracks / clips UI — data from REST</div></footer>
  </div>
`;

const style = document.createElement("style");
style.textContent = `
  body { margin: 0; font-family: system-ui, sans-serif; background: #121212; color: #eee; }
  .bar { padding: 10px 14px; background: #1e1e1e; border-bottom: 1px solid #333; }
  .grid { display: grid; grid-template-columns: 240px 1fr 300px; min-height: 420px; }
  .pane { border-right: 1px solid #2a2a2a; padding: 12px; }
  .center { background: #0d0d0d; }
  .timeline { border-top: 1px solid #2a2a2a; padding: 12px; min-height: 160px; background: #161616; }
  button { margin: 6px 0; padding: 8px 12px; cursor: pointer; background: #2d6cdf; color: #fff; border: none; border-radius: 4px; }
  pre { background: #1a1a1a; padding: 8px; font-size: 11px; overflow: auto; max-height: 200px; }
`;
document.head.appendChild(style);

const out = document.querySelector<HTMLPreElement>("#out")!;

document.querySelector("#btn-health")!.addEventListener("click", async () => {
  try {
    const r = await invoke("orchestrator_health", { baseUrl: null });
    out.textContent = JSON.stringify(r, null, 2);
  } catch (e) {
    out.textContent = String(e);
  }
});

document.querySelector("#btn-projects")!.addEventListener("click", async () => {
  try {
    const r = await invoke("orchestrator_list_projects", { baseUrl: null });
    out.textContent = JSON.stringify(r, null, 2);
  } catch (e) {
    out.textContent = String(e);
  }
});

document.querySelector("#btn-vulkan")!.addEventListener("click", async () => {
  try {
    const r = await invoke("vulkan_discover", {});
    out.textContent = JSON.stringify(r, null, 2);
  } catch (e) {
    out.textContent = String(e);
  }
});

document.querySelector("#btn-timeline")!.addEventListener("click", async () => {
  try {
    const r = await invoke("timeline_resolve_active", {
      payload: {
        playhead_tick: 50,
        sequence: {
          tracks: [
            { id: 1, kind: "Video", lane_index: 1, name: "V1" },
            { id: 2, kind: "Video", lane_index: 0, name: "V2" },
          ],
          clips: [
            { id: 10, track_id: 1, asset_id: 100, span: { in_tick: 0, out_tick: 100 }, src_in_tick: 0 },
            { id: 11, track_id: 2, asset_id: 101, span: { in_tick: 0, out_tick: 100 }, src_in_tick: 0 },
          ],
        },
      },
    });
    out.textContent = JSON.stringify(r, null, 2);
  } catch (e) {
    out.textContent = String(e);
  }
});

document.querySelector("#btn-probe")!.addEventListener("click", async () => {
  const path = window.prompt("Path or URL to probe (ffprobe):", "/tmp/sample.mp4");
  if (!path) return;
  try {
    const base = "http://127.0.0.1:8080";
    const res = await fetch(`${base}/v1/media/probe`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path }),
    });
    out.textContent = await res.text();
  } catch (e) {
    out.textContent = String(e);
  }
});
