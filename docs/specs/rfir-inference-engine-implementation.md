# RFIR Inference Engine — Implementation Plan

**Status:** Draft  
**Last updated:** 2026-06-14  
**Design reference:** [rfir-inference-engine-design.md](./rfir-inference-engine-design.md)  
**Guardrails:** [guardrails-implementation.md](./guardrails-implementation.md)  
**Module boundaries:** [module-boundaries.md](./module-boundaries.md)  
**Onboarding (start here):** [implementer-getting-started-nhuynh30.md](./implementer-getting-started-nhuynh30.md)

---

## 0. Tooling & dependencies to add

Add to `services/model-workers/pyproject.toml` (Poetry) as implementation proceeds:

| Package | Phase | Purpose |
|---------|-------|---------|
| `diffusers>=0.32` | 1 | FLUX, CogVideoX, Wan pipelines |
| `transformers>=4.46` | 1 | Depth Anything, Llama-Guard |
| `accelerate` | 1 | Device map / offload |
| `bitsandbytes` | 1 | NF4 quantization |
| `autoawq` | 1 | FLUX AWQ (or pre-quant weights) |
| `llama-cpp-python` | 2 | Qwen planner on CPU |
| `instructor` or `outlines` | 2 | Structured `ShotList` JSON |
| `opencv-python-headless` | 1 | Image I/O, SSIM |
| `scikit-image` | 2 | SSIM quality gate |
| `sam2` (git dep) | 3 | ROI segmentation |
| `presidio-analyzer` + `presidio-anonymizer` | G1 | PII (orchestrator) |
| `c2pa-python` | G3 | Provenance (orchestrator) |

**Already in repo:** `torch`, `deepiri-gpu-utils`, `renderflow_queue`, FFmpeg (system), Vulkan (`ash`).

**System packages (worker image):** `ffmpeg`, `libvulkan1`, `mesa-vulkan-drivers` or NVIDIA Vulkan ICD.

---

## 1. Overview

This document is the **engineering task list** for building RFIR (RenderFlow Inference Runtime) and wiring it into the existing orchestrator, model-workers, and Vulkan core.

Work is split into **phases**. Each phase has exit criteria, file targets, and dependencies. Do not skip guardrail integration points marked 🛡️.

### Current baseline (what exists today)

| Area | File(s) | State |
|------|---------|-------|
| Video pipeline stub | `services/orchestrator/app/media/text_video_pipeline.py` | Heuristic storyboard; `sdxl` CLI hook |
| AI job lifecycle | `services/orchestrator/app/worker_loop.py`, `job_store.py` | Staged jobs → review |
| Stage runner stub | `services/orchestrator/app/stage_runner.py` | Fake stage payloads |
| Model worker | `services/model-workers/app/model_worker.py` | Causal LM only; FP16 |
| Redis consumer | `services/model-workers/app/redis_worker.py` | Stub scene stages |
| Vulkan graph | `core/render-engine-vulkan/src/graph_schedule.rs` | `FrameGraph`, scheduler |
| Queue contract | `lib/renderflow_queue/` | Redis keys, DLQ, retry |

---

## 2. Repository layout (target)

```
services/model-workers/
  app/rfir/
    __init__.py
    ir/
      __init__.py
      types.py              # RfirNode, RfirGraph, TensorSpec, ShotList
      ops.py                # Op enum + port definitions
      validate.py           # Schema validation
    compiler/
      __init__.py
      builder.py            # ShotList → subgraphs
      fusion.py             # Batch t2i, shared VAE
      memory_plan.py        # Liveness / peak VRAM
      scheduler.py          # Topo sort + barriers
    executor/
      __init__.py
      engine.py             # Main execution loop
      context.py            # Job context, metrics
    ops/
      __init__.py
      plan_shots.py
      t2i_keyframe.py
      depth_estimate.py
      segment_subject.py
      vae.py
      sparse_t2v_window.py
      rife_interpolate.py
      vulkan_export.py      # Handoff to FrameGraph JSON
      ffmpeg_mux.py
    arena.py
    ltc.py
    router.py
    planner.py
    budget.py
    checkpoint.py
    models/
      __init__.py
      registry.py           # Model manifests (id, path, quant, license)
      loader.py             # Warm pool + LRU
      precision.py
  tests/
    test_ir_validate.py
    test_compiler_fusion.py
    test_memory_plan.py
    test_tier_a_e2e.py
    test_budget_downgrade.py
    test_ltc_overlap.py

services/orchestrator/
  app/media/
    cfsv_pipeline.py        # Replaces internals of text_video_pipeline
    rfir_client.py          # Compile + enqueue extended payload
  app/config.py             # RFIR_* settings
  tests/
    test_cfsv_compile.py

core/render-engine-vulkan/
  src/synth/
    mod.rs
    camera.rs               # CameraPath types
    parallax.rs
    depth_warp.rs
    upscale_compute.rs
    composite.rs
  tests/
    synth_schedule.rs

infra/postgres/migrations/
  006_rfir_job_metrics.sql  # Optional: inference_metrics_jsonb on ai_jobs

docs/specs/
  rfir-inference-engine-design.md
  rfir-inference-engine-implementation.md  (this file)
```

---

## 3. Phase 0 — Foundations (Week 1)

**Goal:** IR types, validation, and compiler skeleton with tests. No GPU required.

### Tasks

- [ ] **0.1** Create `app/rfir/ir/types.py` with `RfirNode`, `RfirGraph`, `TensorSpec`, `ShotList`, `Shot`, `CameraPath`, `InferenceBudget`.
- [ ] **0.2** Create `app/rfir/ir/ops.py` — op registry with required inputs/outputs per op (see design doc §5.2).
- [ ] **0.3** Create `app/rfir/ir/validate.py` — validate graph acyclicity, port types, unknown ops.
- [ ] **0.4** Create `app/rfir/compiler/builder.py` — build per-shot subgraph from `ShotList`.
- [ ] **0.5** Create `app/rfir/compiler/scheduler.py` — topological sort; detect cycles.
- [ ] **0.6** Unit tests: `test_ir_validate.py`, `test_compiler_fusion.py` (builder only).
- [ ] **0.7** Add `RENDERFLOW_RFIR_ENABLED` env flag (default `false`) in `app/config.py`.
- [ ] 🛡️ **0.8** Compiler rejects graphs when `policy.ai_enabled` is false (read from job metadata).

### Exit criteria

- `poetry run pytest services/model-workers/tests/test_ir_validate.py` green.
- Sample `ShotList` (3 shots) compiles to valid `RfirGraph` JSON without errors.

### Files touched

| Action | Path |
|--------|------|
| Create | `services/model-workers/app/rfir/**` |
| Modify | `services/orchestrator/app/config.py` |
| Create | `services/model-workers/tests/test_ir_*.py` |

---

## 4. Phase 1 — Tier A end-to-end (Weeks 2–3)

**Goal:** Real keyframe + depth + motion path. First playable MP4 through existing review flow.

### Tasks

#### Model registry and loader

- [ ] **1.1** `models/registry.py` — manifest format:

  ```yaml
  id: flux-schnell-int4
  role: t2i_keyframe
  path: ${RENDERFLOW_MODELS_DIR}/flux-schnell-int4
  quantization: awq_int4
  vram_mb: 7168
  license: apache-2.0
  ```

- [ ] **1.2** `models/loader.py` — load/unload; integrate `deepiri-gpu-utils` for device pick.
- [ ] **1.3** `models/precision.py` — `PrecisionPolicy.resolve(op, device, budget)`.

#### Ops (Tier A)

- [ ] **1.4** `ops/t2i_keyframe.py` — FLUX.1-schnell INT4; batched; 4 steps default.
- [ ] **1.5** `ops/depth_estimate.py` — Depth Anything V2 Small.
- [ ] **1.6** `ops/vulkan_export.py` — emit `FrameGraph` JSON + PNG paths for synth.
- [ ] **1.7** `arena.py` — basic slab allocator for fixed 512×288 RGB + depth tensors.

#### Vulkan synth (minimal)

- [ ] **1.8** `core/render-engine-vulkan/src/synth/camera.rs` — `CameraPath` serde types.
- [ ] **1.9** `core/render-engine-vulkan/src/synth/parallax.rs` — compute pass stub (CPU fallback OK for v1 slice).
- [ ] **1.10** Wire `synth` module in `lib.rs`; extend `FrameGraph` example in tests.

#### Orchestrator integration

- [x] **1.11** `app/media/cfsv_pipeline.py` — `compile_and_run_tier_a(prompt) -> artifact paths`.
- [ ] **1.12** `app/media/rfir_client.py` — serialize graph; extend Redis payload with `compiled_graph_uri`.
- [ ] **1.13** Update `text_video_pipeline.py` to delegate to `cfsv_pipeline` when `RENDERFLOW_RFIR_ENABLED=true`.
- [x] **1.14** Update `stage_runner.py` / `worker_loop.py` to call real RFIR stages (or delegate to Redis worker).
- [ ] **1.15** `redis_worker.py` — invoke `rfir.executor.engine.run_graph()` instead of stub.
- [ ] 🛡️ **1.16** Executor refuses to start if guardrail pre-check failed (read `guardrail_verdict` from payload).

#### FFmpeg fallback

- [ ] **1.17** If Vulkan synth unavailable: `images_to_video` + zoompan filter from `text_video_pipeline.py` as Tier A fallback.

### Exit criteria

- Integration test: submit job → Tier A only → MP4 in review → accept creates asset.
- `scripts/smoke_integration.py` passes with RFIR enabled (or new `smoke_rfir_tier_a.py`).
- Documented model download script: `scripts/download_rfir_models.sh`.

### Dependencies

- `RENDERFLOW_MODELS_DIR` env var
- Optional: FLUX.1-schnell AWQ weights (document license in registry)

---

## 5. Phase 2 — Compiler hardening + Tier B (Weeks 4–5)

**Goal:** Fusion, memory planning, RIFE interpolation, SSIM quality gate.

### Tasks

- [ ] **2.1** `compiler/fusion.py` — merge `t2i_keyframe` nodes across shots (same resolution/steps).
- [ ] **2.2** `compiler/memory_plan.py` — liveness analysis; `peak_vram_mb`; spill/downgrade hints.
- [ ] **2.3** `router.py` — tier assignment heuristics from shot JSON (camera speed, action verbs, duration).
- [ ] **2.4** `planner.py` — Qwen2.5-3B GGUF; structured JSON output schema; 🛡️ output passed to guardrail prompt gate.
- [ ] **2.5** `ops/rife_interpolate.py` — RIFE 4.6 between keyframe pairs.
- [ ] **2.6** SSIM gate in executor: compare RIFE midpoint vs verification keyframe; escalate segment to Tier C plan.
- [ ] **2.7** `budget.py` — `BudgetGovernor.before_node()` downgrade templates.
- [ ] **2.8** Tests: `test_memory_plan.py`, `test_budget_downgrade.py`, `test_tier_b_ssim.py`.

### Exit criteria

- 30s video with mixed Tier A + B shots; automatic downgrade when `max_gpu_seconds` set low.
- Metrics JSON includes `tier_distribution` and `downgrades`.

---

## 6. Phase 3 — Tier C sparse T2V + LTC (Weeks 6–8)

**Goal:** ROI diffusion, latent cache, Vulkan composite over background plate.

### Tasks

- [ ] **3.1** `ops/segment_subject.py` — SAM2 mobile or rembg mask.
- [ ] **3.2** `ops/vae.py` — shared encode/decode.
- [ ] **3.3** `ops/sparse_t2v_window.py` — CogVideoX-2B NF4; ROI crop + pad; sliding windows.
- [ ] **3.4** `ltc.py` — `LatentCacheEntry`, flow warp conditioning, overlap cosine blend.
- [ ] **3.5** Optional: RAFT-small for flow on overlap frames only.
- [ ] **3.6** `core/render-engine-vulkan/src/synth/composite.rs` — ROI layer over background.
- [ ] **3.7** CUDA↔Vulkan handoff: attempt external memory; document fallback path.
- [ ] **3.8** Tests: `test_ltc_overlap.py`, temporal flicker metric on fixture clip.

### Exit criteria

- Tier C shot with subject on Tier A background; no visible seam at ROI boundary on reference fixture.
- Peak VRAM on 8 GB GPU ≤ 7.5 GB (via memory planner downgrade if needed).

---

## 7. Phase 4 — Tier D, checkpointing, cloud (Weeks 9–10)

**Goal:** Hero shots, spot resilience, hybrid routing.

### Tasks

- [ ] **4.1** Tier D full-frame path in `sparse_t2v_window` (no ROI); hard duration cap.
- [ ] **4.2** `checkpoint.py` — serialize at shot boundary; S3/local URIs.
- [ ] **4.3** Resume path in `redis_worker.py` + `REDIS_KEY_JOBS_RETRY`.
- [ ] **4.4** Cloud worker Dockerfile: headless Vulkan/EGL + CUDA base image.
- [ ] **4.5** Hybrid router: `policy.local_only`, `policy.cloud_allowed` in compile step.
- [ ] **4.6** `006_rfir_job_metrics.sql` — `inference_metrics_jsonb` column on `ai_jobs` (optional).
- [ ] **4.7** Cost estimate in metrics: `gpu_seconds * rate_card`.

### Exit criteria

- Kill worker mid-job → retry resumes from next shot.
- Tier D blocked when `max_tier=C` in policy.

---

## 8. Phase 5 — Performance and production (Weeks 11–12)

**Goal:** CUDA graphs, warm pool tuning, observability.

### Tasks

- [ ] **5.1** `torch.compile` on `t2i_keyframe` and `rife_interpolate` for bucketed shapes.
- [ ] **5.2** CUDA graph capture for steady-state Tier A batch.
- [ ] **5.3** Speculative keyframe gen while planner finishes later shots.
- [ ] **5.4** Prometheus-style metrics endpoint on worker (optional): `rfir_gpu_seconds_total`, `rfir_tier_count`.
- [ ] **5.5** Desktop preview: Tauri command to run single-shot Tier A graph locally.
- [ ] **5.6** Update root `README.md` with RFIR env vars and model setup (only when phase 1 exits).

### Exit criteria

- Tier A first preview < 8s on documented reference hardware (RTX 4060).
- 60s 1080p cloud cost < $0.20 on reference tier mix.

---

## 9. Configuration reference

Add to orchestrator and model-workers environment:

| Variable | Default | Description |
|----------|---------|-------------|
| `RENDERFLOW_RFIR_ENABLED` | `false` | Use CFSV pipeline |
| `RENDERFLOW_MODELS_DIR` | `./models` | OSS weight root |
| `RENDERFLOW_RFIR_MAX_GPU_SEC` | `120` | Per-job GPU budget |
| `RENDERFLOW_RFIR_MAX_TIER` | `C` | A, B, C, or D |
| `RENDERFLOW_RFIR_GEN_RES` | `512x288` | Internal gen resolution |
| `RENDERFLOW_RFIR_T2I_STEPS` | `4` | FLUX-schnell steps |
| `RENDERFLOW_RFIR_T2V_STEPS` | `10` | Sparse T2V steps |
| `RENDERFLOW_RFIR_LTC_WINDOW` | `16` | LTC window size |
| `RENDERFLOW_RFIR_LTC_OVERLAP` | `4` | LTC overlap frames |
| `RENDERFLOW_VULKAN_SYNTH` | `auto` | `auto` \| `force` \| `off` |

---

## 10. Redis payload implementation

Modify `RedisJobQueue.push_job` usage in `worker_loop.enqueue_job`:

```python
payload = {
    "prompt": rec.prompt,
    "compiled_graph_uri": graph_uri,
    "budget": {
        "max_gpu_seconds": settings.rfir_max_gpu_sec,
        "max_tier": settings.rfir_max_tier,
    },
    "guardrail_verdict": "allow",  # set by guardrails
    "project": {...},
}
RedisJobQueue(r).push_job(job_id, payload)
```

Worker **must** check `guardrail_verdict == "allow"` before GPU work.

---

## 11. gRPC / proto (deferred)

Track in issue; not blocking v1.

- [ ] `InferenceGraphRequest`, `InferenceProgressEvent` in `proto/grpc/renderflow.proto`
- [ ] Regenerate: `./scripts/gen_proto.sh`
- [ ] Stream node progress in `grpc_service.py`

---

## 12. Testing strategy

| Layer | Tests |
|-------|-------|
| IR | Validation, cycle detection, port mismatches |
| Compiler | Fusion count, peak VRAM estimate, downgrade hints |
| Ops | Mock GPU tensors; snapshot outputs for depth/RIFE |
| Integration | Job round-trip with RFIR enabled |
| Vulkan | `cargo test` synth schedule; golden FrameGraph JSON |
| Performance | Benchmark script `scripts/bench_rfir_tier_a.sh` (non-CI) |

CI (`.github/workflows/ci.yml`): run IR + compiler unit tests without GPU; skip GPU integration unless `self-hosted-gpu` label.

---

## 13. Model licensing checklist

Before shipping each manifest entry, record in `models/registry.py`:

- [ ] License SPDX id (Apache-2.0, MIT, etc.)
- [ ] Commercial use allowed (yes/no)
- [ ] Redistribution of weights (yes/no)
- [ ] Attribution string for About / docs

Do not bundle weights in git; download via `scripts/download_rfir_models.sh` with hash verification.

---

## 14. Rollout plan

| Stage | Audience | Flags |
|-------|----------|-------|
| Dev | Engineers | `RENDERFLOW_RFIR_ENABLED=true` |
| Alpha | Internal projects | Per-project `settings_jsonb.ai.rfir_enabled` |
| Beta | Opt-in users | Default false; UI toggle |
| GA | All AI-enabled projects | Tier A default; C/D behind quality mode |

Feature flag in DB:

```json
{
  "ai": {
    "rfir_enabled": true,
    "max_tier": "C",
    "max_gpu_seconds": 120
  }
}
```

---

## 15. Definition of done (RFIR v1)

- [ ] Tier A/B/C paths implemented and tested.
- [ ] Tier D behind policy + budget.
- [ ] Guardrails integrated at compile, execute, and review (see guardrails doc).
- [ ] Human review required before accept (unchanged).
- [ ] Metrics and cost estimate on every job.
- [ ] Checkpoint resume on shot boundary.
- [ ] Vulkan synth with FFmpeg fallback.
- [ ] Design + implementation docs current.
- [ ] No-AI mode: zero RFIR code paths executed.

---

## 16. Task index (quick reference)

| ID | Task | Phase |
|----|------|-------|
| 0.1–0.8 | IR + compiler skeleton | 0 |
| 1.1–1.17 | Tier A E2E | 1 |
| 2.1–2.8 | Fusion, memory, Tier B | 2 |
| 3.1–3.8 | Tier C + LTC | 3 |
| 4.1–4.7 | Tier D, checkpoint, cloud | 4 |
| 5.1–5.6 | Perf + production | 5 |

---

## 17. Document history

| Date | Change |
|------|--------|
| 2026-06-14 | Initial implementation plan |
