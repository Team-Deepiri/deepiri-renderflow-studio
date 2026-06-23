# Implementer Getting Started — @nhuynh30

**Audience:** Quan Huynh ([@nhuynh30](https://github.com/nhuynh30)) — primary implementer for RFIR inference + guardrails  
**Status:** Draft  
**Last updated:** 2026-06-14

This is your **single entry point**. Read this first, then the three deep specs:

| Doc | What it is |
|-----|------------|
| [rfir-inference-engine-design.md](./rfir-inference-engine-design.md) | **What** we are building and **why** (CFSV + RFIR) |
| [rfir-inference-engine-implementation.md](./rfir-inference-engine-implementation.md) | **How** to build RFIR — phases, files, checkboxes |
| [guardrails-implementation.md](./guardrails-implementation.md) | **How** to build safety/ethics/legal gates |

---

## 1. What you are building (30-second version)

RenderFlow is a **native video editor** (like Premiere/Resolve) with an **optional AI copilot**. Today, AI video generation is a **stub** (`text_video_pipeline.py` calls a fake `sdxl` CLI; `stage_runner.py` returns hardcoded JSON).

You are implementing:

1. **RFIR** — a compiled inference engine that generates video **cheaply** by only running diffusion on keyframes and small regions, then using **Vulkan + FFmpeg** for motion and stitching.
2. **Guardrails** — policy, safety, ethics, and legal checks **before, during, and after** generation so we never ship harmful or non-compliant outputs.

Nothing auto-commits to the timeline. Users **review and accept** (already wired in `ai_jobs.py`).

---

## 2. The big idea (CFSV)

**Compositor-First Sparse Video** — do not diffuse every frame.

| Tier | % of shots | What happens | GPU cost |
|------|------------|--------------|----------|
| **A** | ~70% | 1 FLUX keyframe + depth + Vulkan camera motion | Cheapest |
| **B** | ~20% | 2 keyframes + RIFE interpolation | Medium |
| **C** | ~8% | Diffusion on **subject ROI only** (SAM2 mask) | Higher |
| **D** | ~2% | Full-frame hero shot (short, budget-gated) | Highest |

Full T2V for 60s ≈ **$1–2** cloud. CFSV target ≈ **$0.08–0.20**.

---

## 3. Where code lives today (your touch points)

```
services/orchestrator/
  app/worker_loop.py          ← job state machine; you hook real stages here
  app/stage_runner.py         ← REPLACE stubs with RFIR stage calls
  app/media/text_video_pipeline.py  ← REPLACE with cfsv_pipeline delegation
  app/api/routers/ai_jobs.py  ← job create/accept/reject; add guardrail on create
  app/guardrails/             ← YOU CREATE (policy, prompt, output guards)

services/model-workers/
  app/redis_worker.py         ← REPLACE stub with rfir.executor
  app/model_worker.py         ← today: text LLM only; reference for GPU patterns
  app/rfir/                   ← YOU CREATE (IR, compiler, executor, ops)

core/render-engine-vulkan/
  src/synth/                  ← YOU CREATE (parallax, composite, upscale)

lib/renderflow_queue/         ← Redis contract; extend payload only
infra/postgres/migrations/    ← 006_guardrails.sql, optional 006_rfir_metrics
```

---

## 4. Day 1 setup (your machine)

### 4.1 Clone layout

Per root [README.md](../../README.md), sibling clone for GPU utils:

```
parent/
  deepiri-gpu-utils/
  deepiri-renderflow-studio/   ← this repo
```

### 4.2 Orchestrator

```bash
cd services/orchestrator
poetry install
./scripts/run_orchestrator.sh
# Health: http://127.0.0.1:8080/health
```

### 4.3 Docker (Postgres + Redis + MinIO)

```bash
docker compose -f infra/docker/docker-compose.yml up -d
export REDIS_URL=redis://127.0.0.1:6380/0
export DATABASE_URL=postgresql://renderflow:renderflow@127.0.0.1:5433/renderflow
```

### 4.4 Model workers

```bash
cd services/model-workers
poetry install
poetry run python -m app.redis_worker
```

### 4.5 Verify baseline

```bash
cd services/orchestrator
poetry run python ../../scripts/smoke_integration.py
cargo test --manifest-path ../../core/render-engine-vulkan/Cargo.toml
```

### 4.6 GPU

- NVIDIA: CUDA 12.x + driver; `deepiri-gpu-utils` picks device.
- Apple: MPS path exists in `model_worker.py` but RFIR v1 targets CUDA first; document MPS gaps.

### 4.7 Models directory

```bash
export RENDERFLOW_MODELS_DIR=$HOME/renderflow-models
mkdir -p $RENDERFLOW_MODELS_DIR
# After you add scripts/download_rfir_models.sh — run it once
```

---

## 5. Your first milestone (Phase 0 + Phase 1)

**Goal:** One real Tier-A shot → MP4 → job reaches `review` → accept creates asset.

### Week 1 — Phase 0 (no GPU)

1. Create `services/model-workers/app/rfir/ir/types.py` — `RfirNode`, `RfirGraph`, `ShotList`.
2. Create `ir/validate.py` + `compiler/builder.py` — compile 3-shot fixture to JSON.
3. Tests: `services/model-workers/tests/test_ir_validate.py`.

**Done when:** `poetry run pytest` green on IR tests.

### Weeks 2–3 — Phase 1 (Tier A)

1. `models/registry.py` + `loader.py` — FLUX.1-schnell AWQ via **diffusers**.
2. `ops/t2i_keyframe.py` + `ops/depth_estimate.py` (Depth Anything V2).
3. `executor/engine.py` — walk graph, run ops.
4. `cfsv_pipeline.py` in orchestrator — compile graph, enqueue Redis payload.
5. Wire `RENDERFLOW_RFIR_ENABLED=true`.
6. FFmpeg fallback if Vulkan synth not ready (zoompan filter).

**Done when:** `POST /v1/jobs` with video prompt → MP4 on disk → `accept` creates video asset.

Checklist detail: [rfir-inference-engine-implementation.md § Phase 0–1](./rfir-inference-engine-implementation.md).

---

## 6. Guardrails — what you build in parallel

Start **Phase G0–G1** alongside RFIR Phase 0:

| Order | Task | File |
|-------|------|------|
| 1 | Migration `006_guardrails.sql` | `infra/postgres/migrations/` |
| 2 | `policy_gate.py` — block if `projects.ai_enabled=false` | `app/guardrails/` |
| 3 | `prompt_guard.py` — Llama-Guard-3-1B + Presidio PII | same |
| 4 | Wire `create_ai_job` — no enqueue on `block` | `ai_jobs.py` |

Full plan: [guardrails-implementation.md](./guardrails-implementation.md).

**Non-negotiable:** S4 child-safety category always blocks. No feature flag override in prod.

---

## 7. Tools you will use (best available)

Do **not** reinvent these — use the libraries in the design doc §6:

| Job | Library |
|-----|---------|
| Image/video diffusion | `diffusers` (FLUX, Wan, CogVideoX) |
| Quantization | `autoawq`, `bitsandbytes` |
| Shot planning LLM | `llama-cpp-python` + Qwen2.5-3B GGUF |
| Structured JSON | `instructor` + Pydantic |
| Interpolation | Practical-RIFE |
| Depth | Depth Anything V2 (`transformers`) |
| Masks | SAM 2 `sam2-hiera-tiny` |
| Safety | Llama-Guard-3-1B |
| PII | Presidio |
| Provenance | `c2pa-python` |
| GPU pick | `deepiri-gpu-utils` |
| Queue | `renderflow_queue` |

---

## 8. Redis job payload (contract you must implement)

Orchestrator pushes:

```json
{
  "job_id": "uuid",
  "payload": {
    "prompt": "...",
    "compiled_graph_uri": "file://.../graph.json",
    "guardrail_verdict": "allow",
    "budget": {"max_gpu_seconds": 120, "max_tier": "C"},
    "project": {"fps_num": 24, "resolution_w": 1920, "resolution_h": 1080}
  }
}
```

Worker **refuses** if `guardrail_verdict != "allow"`.

---

## 9. Suggested branch strategy

| Branch | Work |
|--------|------|
| `nhuynh30/rfir/phase-0-ir` | IR + compiler + tests |
| `nhuynh30/rfir/phase-1-tier-a` | FLUX + depth + FFmpeg path |
| `nhuynh30/guardrails/g0-g1` | Schema + policy + prompt gates |
| `nhuynh30/rfir/phase-2-tier-b` | RIFE + SSIM |
| `nhuynh30/rfir/phase-3-tier-c` | Wan + LTC + SAM2 |

Merge to `dev` after each phase exit criteria. Keep PRs **small and vertical** (one phase per PR where possible).

---

## 10. Who to ask / what not to block on

| Topic | Notes |
|-------|-------|
| **Vulkan synth** | Phase 1 can ship FFmpeg fallback; parallax in Rust can lag Tier A slightly |
| **Wan2.1 diffusers** | If pipeline not merged yet, use CogVideoX-2B for Phase 3 |
| **CSAM hash API** | Legal must enable Thorn/PhotoDNA — stub hook only until sign-off |
| **deepiri-gpu-utils** | Sibling repo; ping team if device detection wrong |

---

## 11. Success criteria (v1 ship)

- [ ] Tier A/B/C paths work on RTX 4060 8 GB (with downgrade)
- [ ] Guardrails block unsafe prompts before GPU
- [ ] C2PA or JSON provenance on outputs
- [ ] Human review still required
- [ ] 60s video cloud cost < $0.20 on reference mix
- [ ] Docs match code

---

## 12. Reading order

1. This file  
2. [rfir-inference-engine-design.md](./rfir-inference-engine-design.md) — full design  
3. [rfir-inference-engine-implementation.md](./rfir-inference-engine-implementation.md) — your task list  
4. [guardrails-implementation.md](./guardrails-implementation.md) — safety task list  
5. [architecture.md](./architecture.md) + [module-boundaries.md](./module-boundaries.md) — repo rules  

---

## 13. Document history

| Date | Change |
|------|--------|
| 2026-06-14 | Initial onboarding doc for @nhuynh30 |
