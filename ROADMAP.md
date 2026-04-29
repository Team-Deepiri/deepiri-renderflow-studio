# Deepiri Renderflow Studio — Product & Engineering Roadmap

This document is the **single narrative** for what we are building, why it exists, and how implementation should proceed. Anyone joining the project should be able to read this, align with the **vision**, pick work from **phases**, and understand **constraints** (native-first, Vulkan, optional AI, no-AI parity, vendored Deepiri code).

---

## 1. Vision (what we are building)

**Deepiri Renderflow Studio** (`deepiri-renderflow-studio`) is a **native desktop creative application** in the class of Premiere Pro, DaVinci Resolve, After Effects, and Blender—not a website-as-product. It targets:

| Domain | Intent |
|--------|--------|
| **Video editing (NLE)** | Multi-track timeline, trimming, nesting, proxies, export. |
| **VFX & compositing** | Layer stacks, mattes, color pipeline, GPU-accelerated effects. |
| **Motion graphics** | Keyframed 2D/2.5D motion, titles, procedural elements. |
| **3D / DCC-style workflow** | Scene graph, cameras, materials, animation; depth integrated with the timeline—not a bolt-on toy. |
| **Audio / voice production** | Dialogue, music, SFX buses; monitoring and export aligned to picture. |
| **Optional AI** | Copilot that proposes stages (storyboard → layout → assets → timeline commits) **without blocking the UI**. |
| **No-AI mode** | **First-class**: every AI path has a manual equivalent; AI can be disabled per project or org policy. |

**UX north star:** Feels like **professional video editing software**:

- Large **toolbar** of editing and creation tools.
- **Left:** project / file explorer (assets, bins, import/export).
- **Center:** **program monitor** driven by a **Vulkan** preview surface; timeline transport (play, scrub, JKL).
- **Right:** **AI chat / task panel** with explicit actions (e.g. “Create scene”, “Generate audio”, staged pipelines). In **manual mode**, this panel collapses or hides; the rest of the app is unchanged.
- **Bottom:** **timeline** (video/audio tracks), with inspectors / keyframes / mixer / render jobs in supporting panels.

**Deployment model:** **Hybrid AI**—local GPU inference and cloud/API backends are both supported; the desktop app must not assume always-online or always-local.

---

## 2. Technical principles (non-negotiables)

1. **Native-first** — Primary product is a **Tauri** desktop shell talking to a **Rust/C++ core**. There is **no standalone web UI** as the product; any web tech inside the shell is for the **editor chrome only**, not a replacement for the engine.
2. **Vulkan-first rendering** — Preview and compositing target **Vulkan**; **CUDA** (NVIDIA) and **Metal** (Apple) are **GPU compute** backends where needed (PyTorch workers, optional native compute passes), not excuses to skip a real Vulkan compositor.
3. **Timeline engine in native code** — Clip resolution, timebase, keyframes, and audio clock logic live in **`core/timeline-engine-rs`** (and C++ where justified), not in Python or the UI layer.
4. **Media via FFmpeg** — Decode/encode, proxies, thumbnails, waveforms—**FFmpeg** is the industry spine.
5. **Audio via JUCE** — **`core/audio-engine-juce`**: routing, monitoring, FX chains, export/bounce path; sync to timeline sample clock.
6. **AI is async** — Jobs: `queued → preparing → running → review → accepted/rejected → committed`. UI stays responsive; results become **normal assets and timeline edits** once accepted.
7. **No-AI parity** — Disabling AI must not remove export, preview, or editorial depth—only copilot features.
8. **Reuse Deepiri packages** — Install **`deepiri-gpu-utils`** via **Poetry** (e.g. Git `main`). Shared worker Redis types live in-repo at **`lib/renderflow_queue/`** (distribution **`deepiri-renderflow-worker-queue`**). Reserve **`vendor/deepiri/**`** only for snippets without a proper package yet (**`helox`**, **`synapse`**, **`sugarglider`**), with provenance headers.
9. **Data layer** — **PostgreSQL** (metadata), **Redis** (queues/cache/pub-sub), **S3-compatible + local disk** (blobs, renders, proxies), **gRPC** between desktop core and services.

---

## 3. Repository map (where work happens)

| Path | Responsibility |
|------|----------------|
| `apps/desktop-tauri/` | Tauri app: window, menus, capabilities, UI host, IPC to core. |
| `core/timeline-engine-rs/` | Deterministic timebase, clips, keyframe evaluation hooks. |
| `core/render-engine-vulkan/` | Render graph, passes, GPU resources, preview/export orchestration. |
| `core/audio-engine-juce/` | JUCE integration boundary (native C++ + FFI). |
| `services/ai-orchestrator-fastapi/` | FastAPI: job API, auth hooks, DB, Redis, stage streaming. |
| `services/model-workers-pytorch/` | PyTorch workers: CUDA/MPS/CPU; model loading and inference. |
| `proto/grpc/` | `.proto` contracts; desktop ↔ orchestrator. |
| `infra/postgres/migrations/` | Schema evolution. |
| `infra/docker/` | Local Postgres, Redis, MinIO. |
| `vendor/deepiri/` | Vendored Deepiri code only. |
| `docs/specs/` | Architecture, wireframes, deep specs. |

**Companion reading:** [docs/specs/architecture.md](docs/specs/architecture.md), [docs/specs/studio-wireframe.md](docs/specs/studio-wireframe.md), root [README.md](README.md).

---

## 4. Product maturity model (how we measure “closer to vision”)

Use these **capability levels** so roadmap items are not vague:

| Level | Meaning |
|-------|---------|
| **L0** | Spec + interfaces only (proto, schema, empty modules). |
| **L1** | Runnable locally: smoke tests, fake data, one happy path. |
| **L2** | Real subsystem: correct behavior on reference fixtures, perf budget drafted. |
| **L3** | Production-shaped: crash recovery, telemetry, codec matrix, CI. |

**North-star acceptance (future):** A user can **import footage**, **edit on timeline**, **preview in Vulkan**, **mix audio in JUCE**, **export** with **AI off**; with **AI on**, run a **staged job** that lands as **versioned assets** and **optional timeline patches**, with **reject/undo**.

---

## 5. Roadmap phases (sequenced for a real studio, not a demo)

Phases are **overlapping**: later phases start as soon as interfaces exist—do not wait for “perfect” UI.

### Phase A — Foundations & contracts (current baseline → L1)

**Goal:** Anyone can clone, run core tests, run orchestrator, apply DB migrations, and understand IPC.

| Work item | Outcome |
|-----------|---------|
| Workspace hygiene | Root README free of unrelated template noise; single source of truth for build commands. |
| `timeline-engine-rs` | Rational time, frame↔tick, `ClipSpan`, multi-track `Sequence::active_clips_at` (lane-ordered), Tauri `timeline_resolve_active` command. |
| `render-engine-vulkan` | Render graph model + pass ordering tests; hook points for FFmpeg upload textures. |
| `proto/grpc` | `Project`, `Asset`, `Render`, `AISession` services split; versioning strategy (`v1`, `v2`). |
| PostgreSQL | Full schema: projects, sequences, tracks, clips, effects, scenes, `ai_jobs` + stages + artifacts, `render_jobs`, audit. |
| Docker compose | Postgres + Redis + MinIO; documented ports (avoid clashing with host defaults). |
| Vendored modules | Expand `vendor/deepiri/*` with real copies from upstream + commit hashes; locate **sugarglider** or document absence. |

**Exit criteria:** `cargo test` on core crates green; `uvicorn` health + one job round-trip; `docker compose up` applies migrations.

---

### Phase B — Desktop shell & editor chrome (L1 → L2)

**Goal:** Persistent **studio layout**: explorer | monitor | (optional) AI | timeline; **manual mode** toggles AI panel only.

| Work item | Outcome |
|-----------|---------|
| Tauri capabilities | FS scopes for project roots, drag-drop from OS, secure paths. |
| UI state | Project model binding: bins, selection, playhead, zoom, snap. |
| Command palette | All actions invokable without AI (parity). |
| Transport | Play/pause/scrub; timecode display; FPS + drop-frame correctness delegated to timeline engine. |

**Exit criteria:** Open/save project shell; scrub timeline mock; AI panel hide/show does not break layout.

---

### Phase C — Media pipeline & assets (L2)

**Goal:** **FFmpeg** ingest, proxies, thumbnails, waveforms; assets in DB + on disk/S3.

| Work item | Outcome |
|-----------|---------|
| Ingest service / core worker | Hash, transcode proxy, extract metadata. |
| Cache policy | Local LRU + Redis keys for “is proxy ready”. |
| Asset browser | Bind to real files; relink missing media. |

**Exit criteria:** Import 1080p clip → proxy plays in monitor within target latency (document p95).

---

### Phase D — Timeline & playback (L2 → L3)

**Goal:** Frame-accurate **multi-track** composition; audio sample lock.

| Work item | Outcome |
|-----------|---------|
| Clip model | Trim, slip, slide, speed, nested sequences. |
| Keyframes | Spatial/temporal; interpolation shared with motion and 3D properties. |
| Audio clock | JUCE transport locked to timeline `ticks_per_second` and `sample_rate`. |
| Stress tests | Long playback (e.g. 30 min) A/V drift ≤ 1 frame equivalent. |

**Exit criteria:** Deterministic unit tests for edge cases (zero-length clip, overlapping rules, nested seq).

---

### Phase E — Vulkan preview & compositing (L2 → L3)

**Goal:** **Program monitor** shows **composited** result: color-managed stack, basic blend modes, transforms.

| Work item | Outcome |
|-----------|---------|
| Texture pipeline | Upload decoded frames / GPU buffers; handle aspect & safe margins. |
| Color | Linear working space; display transform hook (OCIO-style later). |
| Effect stack | Non-destructive per-clip FX; parameter animation. |
| GPU compute | Optional passes: denoise, resize, optical-flow-assisted retiming (CUDA/Metal where appropriate). |

**Exit criteria:** Benchmark: 1080p60 multi-layer preview on reference hardware; fallback CPU path documented.

---

### Phase F — Export & render farm (L2 → L3)

**Goal:** Background **render jobs**, resumable outputs, presets (ProRes/H264/etc. per legal packaging).

| Work item | Outcome |
|-----------|---------|
| Render queue | `render_jobs` table + worker process. |
| FFmpeg export | Match timeline; audio mux; timecode burn-in optional. |
| S3/local | Output URI + checksum + manifest. |

**Exit criteria:** Power loss mid-render → resume or clean fail with user-visible status.

---

### Phase G — 3D & motion graphics (L2, long arc)

**Goal:** **Scene graph** tied to timeline: cameras, lights, meshes, materials; motion graphics primitives.

| Work item | Outcome |
|-----------|---------|
| Scene DB | `scenes`, `scene_nodes`, `animation_curves` wired to engine. |
| Import | glTF/OBJ first; rigging later. |
| Viewport | Same Vulkan path as 2D comp; depth buffer + picking. |

**Exit criteria:** One full shot: 3D environment + 2D titles + color grade + audio in one export.

---

### Phase H — AI orchestration (hybrid, L2 → L3)

**Goal:** **Staged** copilot: chat + buttons; workers on **PyTorch**; events on **Redis**; metadata in **Postgres**; artifacts in **S3/disk**.

| Work item | Outcome |
|-----------|---------|
| gRPC `AISession` | Submit job, stream stage updates, cancel, commit artifact. |
| Worker pool | Redis queue consumer; GPU selection via **`deepiri-gpu-utils`** + optional `helox` patterns. |
| Cyrex-style backpressure | Apply backpressure on **`lib/renderflow_queue`** / worker pool concurrency caps. |
| Synapse events | `vendor/deepiri/synapse` models for render/AI audit streams. |
| Safety | Prompt/asset audit log; org policy “AI disabled”. |

**Exit criteria:** AI off: zero network calls required for edit session; AI on: job failure isolated—project still open.

---

## 6. Cross-cutting work (every phase)

| Track | What to maintain |
|-------|------------------|
| **Security** | Tauri capability least-privilege; no arbitrary remote code from AI without sandbox. |
| **Reliability** | Autosave journal; crash recovery; corrupt project detection. |
| **Performance SLOs** | UI p95 &lt; 25 ms interaction; 60 fps preview targets documented per tier. |
| **Testing** | Golden media fixtures; timeline property tests; gRPC contract tests. |
| **Docs** | Update `docs/specs/` when behavior changes; keep roadmap phase checkboxes honest. |
| **Licensing** | FFmpeg/JUCE/plugin codecs: per-platform legal matrix. |

---

## 7. Math & quality bar (reference for implementers)

Implementers should not guess timing or compositing—follow the engine spec:

- **Rational time:** `t = num / den` for all internal scheduling; avoid float drift across long timelines.
- **Frame index ↔ time:** `t_seconds = frame_index * fps_den / fps_num`.
- **Audio samples:** `sample_index = round(t_seconds * sample_rate)` with documented rounding at boundaries.
- **Premultiplied alpha:** `C_out = C_a + C_b * (1 - A_a)`, `A_out = A_a + A_b * (1 - A_a)`.
- **3D:** Standard `MVP` chain; quaternion slerp for rotations; skinning `M_skin = M_global * inv(M_bind)`.

Fuller detail lives in architecture spec and future `docs/specs/math.md` if split out.

---

## 8. Vendoring playbook (Deepiri packages)

When pulling from upstream:

1. Copy minimal surface into `vendor/deepiri/<package>/`.
2. Add file header: **source path**, **commit hash**, **Renderflow adaptation note**.
3. Rewrite imports to stay **internal** to Renderflow.
4. Add a one-line entry in `vendor/deepiri/README.md` changelog table (date, commit, files).
5. Prefer **thin adapters** in `core/` or `services/` over editing vendored files—patch upstream copies only when necessary.

**Sugarglider:** If the package is not in this workspace, track discovery in an issue: either vendor when found or replace with `deepiri-shared-utils` patterns—**do not block Phase A–E** on it.

---

## 9. How individual contributors should use this roadmap

1. **Read sections 1–2** to internalize vision and constraints.
2. **Identify your phase** (A–H); start only from **Exit criteria** of the previous phase unless you own an interface.
3. **Touch minimal surface**: extend `proto/`, schema, then core, then UI.
4. **Ship vertical slices**: e.g. “import → clip on timeline → one frame in Vulkan” beats ten half-finished panels.
5. **Keep no-AI parity**: if you add an AI button, add or document the manual menu path.
6. **Update this file** when a phase completes or scope shifts (date + short note at bottom).

---

## 10. Risks & mitigations

| Risk | Mitigation |
|------|------------|
| Scope explosion (Premiere + Blender + AE at once) | Strict phase gates; 3D deep features after NLE+Vulkan+export are credible. |
| A/V drift | Timeline + JUCE owned by same clock model; long-run tests. |
| Codec/legal | Abstract encoder backends; document what ships per platform. |
| AI reliability | Human review stage; never auto-destruct source media. |
| Vendor drift | Provenance headers + periodic re-sync playbook. |

---

## 11. Document history

| Date | Note |
|------|------|
| 2026-04-29 | Initial roadmap: vision, principles, phases A–H, contributor playbook, aligned with native/Vulkan/JUCE/FFmpeg/hybrid AI/no-AI parity and vendored Deepiri strategy. |

---

*This roadmap is descriptive of intent and sequencing; detailed task breakdown belongs in issues per phase. When in doubt, optimize for **native performance**, **deterministic editing**, and **manual-mode completeness**.*
