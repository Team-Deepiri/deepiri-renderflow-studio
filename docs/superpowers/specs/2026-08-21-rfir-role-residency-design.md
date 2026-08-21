# RFIR Role Residency — Design

**Status:** Ready for implementation  
**Date:** 2026-08-21  
**Owners:** RenderFlow AI / model-workers  
**Implementer:** Quan Huynh ([@nhuynh30](https://github.com/nhuynh30))  
**Related:** [rfir-inference-engine-design.md](../../specs/rfir-inference-engine-design.md), [registry.py](../../../services/model-workers/app/rfir/models/registry.py)

**Gate:** run `poetry run pytest tests/test_residency_math.py -v` in `services/model-workers` and get a green suite **before** writing fetch, LRU, or quantization code. The math module is the contract.

---

## Locksmith

You were right to bring this here. 30 GB is not one model. It is a prepaid optionality bill.

### 1. Reframe the Reality

Stop asking “how do we shrink 30 GB of weights without losing quality?”

Ask: **why is unused capability resident on the user’s disk?**

Capability is “this machine can run Tier A–D at current quality when asked.” That does not require every role sitting in `RENDERFLOW_MODELS_DIR` on day one. The wall is **residency**, not **representational capacity**.

The compiler already knows the covering set of roles before a GPU is touched. VRAM already load/evicts (`loader.unload_model`). Disk never got that treatment. `scripts/download_rfir_models.py` snapshots FLUX **and** SDXL-Turbo **and** CogVideoX-2B as fp16.

### 2. The Outsider Loop

Treat weights like the job queue, not like the app binary.

Qwen already downloads one GGUF via `allow_patterns`. Diffusion does not. Apply the same slice to every role: fetch what the compiled graph names, pin the tiny always-on pack, LRU the giants.

The “truck” metaphor maps here, not to a chimera model:

- You cannot weld FLUX, SDXL, CogVideoX, Qwen, SAM2, and RIFE into one weight tensor. They are different architectures. `θ_i − θ_j` is undefined across them.
- You **can** build the truck out of the load: the compiled graph **is** the load plan. Each edge names a role; the fetcher covers those roles and no others.
- “Stack so it won’t fall” is a pin set (small, high-frequency) plus LRU on T2I/T2V.
- “One cell block” is content-addressed files already keyed by `sha256` on `ModelManifest`.
- “Popcorn / counter-loop / random queue” is a **fetch** priority queue, not a random permutation of diffusion timesteps. Random pop of the current job’s missing shards is strictly worse than demand-priority. Random **is** allowed for prefetch of roles not in the current job.

### 3. The System Fix

Three rules, so a 30 GB install cannot exist:

1. **One canonical artifact per role.** Default T2I is one model, not FLUX plus SDXL. SDXL-Turbo is opt-in for 8 GB cards (`RENDERFLOW_RFIR_T2I_MODEL=sdxl-turbo-fp16`).
2. **Quantized weights are the CUDA disk form.** SVDQuant / AWQ INT4 of the **same** architecture (ICLR 2025, MIT HAN Lab). MPS stays fp16 — no `bitsandbytes`/`autoawq` on Metal.
3. **Fetch by compiled graph.** `ensure_roles(required_roles(graph))`. Installer ships the pin pack only.

Same models. Same ops. Same quality after first fetch of that role. Disk drops because unused roles are not prepaid.

---

## Applied mathematics (discovery, not decoration)

### System (plain language)

Several specialist machines sit on disk. A job is a recipe that only some of them will touch. Today we copy every machine onto every user’s drive before they cook. We should copy a machine when the recipe names it, keep the small ones around because almost every recipe uses them, and let the huge ones leave if they have not been named in a while.

### Inventory

| Entity | What it is |
|---|---|
| Role | A job the graph can name (`t2i_keyframe`, `sparse_t2v`, …) |
| Model artifact | Bytes on disk that implement one role |
| Compiled graph | Recipe produced **before** GPU work |
| Pin set | Roles that stay on disk |
| Hot set | Roles currently on disk |
| Job | One generation request |

| Measurable | Unit |
|---|---|
| `s_r` size of role r | bytes |
| `p_r` P(role in a random job) | dimensionless |
| `W` LRU window | jobs |
| `D_t` demand of job t | set of roles |
| `H_t` hot set | set of roles |
| Disk at rest | bytes |
| Fetch miss | bytes / seconds |
| Quality vs fp16 teacher | SSIM / FID on a frozen eval set (later phase) |

**Hard constraints:** quality of an invoked role equals that role’s current teacher (identity, not “close enough chimera”). VRAM still obeys the existing warm pool. MPS cannot use CUDA-only quant.

**Soft constraints:** first-job fetch latency; cloud image size.

### Representations

- Venn: catalog C vs hot H vs demand D. Miss = D \ H.
- Time series: disk vs job index under LRU.
- Hand-worked: see `tests/test_residency_math.py::test_working_set_window_1_beats_prepaid`.

### Invariants

| Kind | Statement | Break attempt |
|---|---|---|
| Conserved | Product capability = catalog C, independent of H | Removing a role from C **does** drop capability. Removing it from H does not, until a job needs it and fetch fails. |
| Bounded | Disk ≤ Σ s_r always | Dual-shipping T2I **exceeds** a single-T2I bound. That is the bug. |
| Monotone | E[disk] increases with W | Confirmed: `resident_probability(p, W)` is increasing in W for p in (0,1). |
| Structural | `required_roles(graph)` is a function of ops only | Vulkan/ffmpeg ops contribute nothing. |

**Failed invariant:** “final image is independent of timestep order.” The probability-flow ODE is `dx/dt = f(x,t)` — time-inhomogeneous. Permuting t is not a valid integrator. Adaptive **step size** (DPM-Solver++) is real; random **step order** is not. That guess is recorded as dead.

**Failed invariant:** “residuals θ_FLUX − θ_SDXL are low-rank.” Different parameter spaces. `refuse_cross_architecture_residual` encodes the refusal.

### Symmetries

- Relabeling jobs: if jobs are exchangeable, only `p_r` matters, not identity. Licenses the LRU formula.
- Description: bytes, not “GB of capability.” Equations use bytes.
- Not symmetric: FLUX vs SDXL vs CogVideoX (architectures). Forbids chimera-subtraction.

### Dimensionless groups

Let `S = Σ_r s_r` (catalog, one T2I).

- `ρ = E[disk] / S` — residency compression. Today with dual T2I, ρ > 1 relative to one-T2I catalog.
- `α = P(D ⊆ H)` — zero-wait hit rate.
- `η_r = quality_r(disk artifact) / quality_r(fp16)` — must be 1 for identity (phase 1) or ≥ a measured threshold after SVDQuant (phase 2).

Limiting cases:

- `W → ∞` ⇒ `ρ → 1` (prepaid catalog). This is today’s download script.
- `W = 1`, pin = small roles, `p_t2i = 1`, `p_t2v = 0.1` ⇒ ρ ≈ 0.5 vs dual-T2I prepaid (see tests).
- `p_t2v → 0` (Tier A/B only users) ⇒ T2V bytes vanish from E[disk].

### State variables

Markov state for disk: the hot set H, or equivalently last-used job index per role. History beyond that does not change fetch decisions. Demand D is known at compile time — **information structure is full for the current job**. That is the underutilized ingredient.

### Optimization

- **Decision:** which roles to pin, LRU window W, whether to store INT4 vs fp16 per role, whether to keep a T2I fallback.
- **Objective:** minimize E[disk] + λ E[miss seconds], subject to η = 1 for invoked roles.
- **Hard:** cannot serve a role that is neither hot nor fetchable; cannot LoRA-merge distinct architectures.
- **Soft:** first-job wait; installer size.
- **Info:** D_current is known; future D is known only as CFSV mix `p_r`.

### Conceptual model

Online caching with a known reference string prefix (the current graph) plus a stochastic tail (future jobs). Not a diffusion ODE. Not a single DiT.

### Novel equations (the ones we will actually test)

**Role-working-set law.** Independent jobs, LRU of the last W jobs, pin set P:

```
P(r hot) = 1                       if r ∈ P
P(r hot) = 1 − (1 − p_r)^W         otherwise

E[disk] = Σ_r s_r · P(r hot)
```

Miss for job t:

```
miss_bytes(t) = Σ_{r ∈ D_t \ H_t} s_r
```

Compression:

```
ρ = E[disk] / S
```

Fetch pop (current job):

```
order = current-job misses first, then descending s_r
```

These are the equations in `app/rfir/models/residency.py`. They are measurable: sizes from disk, `p_r` from `graph.metadata["tier_distribution"]` logs, W a config int.

**Same-architecture 4-bit (phase 2, not invented here).** SVDQuant (Li et al., ICLR 2025, arXiv:2411.05007): within one matrix W of one model, absorb outliers in a high-precision low-rank branch `U Σ V^T`, quantize the residual to 4-bit. Published result: ~3.5× memory cut on 12B FLUX with preserved visual quality, Nunchaku fused kernels. We cite this; we do not re-derive it. Disk artifact for CUDA T2I becomes the SVDQuant/AWQ package, not fp16. Measure η on our 512×288 keyframe eval before flipping the default.

**Same-base multi-teacher (phase 3, gated).** CollectionLoRA (2026) and MT-DMD distill **LoRAs of one base**, not FLUX+SDXL+Cog into one student. Allowed later: distill FLUX-schnell and an in-family variant into one T2I **if** a bake-off on RFIR prompts holds η. Forbidden in v1: one chimera for all roles.

**Wan 2.1-T2V-1.3B swap (phase 3, gated).** Already the intended primary in the RFIR design spec. Official card: ~8.2 GB VRAM, 480p, Apache-style OSS. Keep CogVideoX-2B as fallback until a Tier C/D bake-off on our shots. This is a role swap inside `sparse_t2v`, not a merge.

### Proof strategy

Working-set formula: binomial, elementary. Tested by hand-worked numbers in pytest (constructive). ODE permutation claim: **refuted** by time-dependence of `f(x,t)`; we do not implement it.

### Simplifications

- Jobs independent. Real users batch similar tiers; that **raises** hit rate, so independence is conservative for disk savings.
- `p_r` from the design mix, not production logs. Replace with empirical frequencies when jobs exist.
- VAE size folded into T2V checkpoint (already shared repo in the download script).

### Experiments before solutions

1. **Now:** `test_residency_math.py` (no GPU).
2. **After fetch lands:** log `hot_bytes`, `miss_bytes`, `roles` per job; compare to E[disk].
3. **Phase 2:** SSIM/FID of INT4 FLUX vs fp16 FLUX on a frozen 32-prompt keyframe set at 512×288, 4 steps.
4. **Phase 3:** Wan 1.3B vs CogVideoX-2B on frozen Tier C/D shots.

### Domain of validity

- Holds for heterogeneous role catalogs with a compiler that names roles before fetch.
- Fails if a job can require a role not in the graph (hidden loader). Do not let `load_model` pull undeclared ids.
- SVDQuant path fails on MPS — keep fp16.
- Chimera distillation fails across architectures — refuse it.

### Failed guesses

| Guess | Why it failed |
|---|---|
| Random timestep permutation preserves samples | ODE is time-inhomogeneous |
| LoRA of (FLUX − SDXL − Cog) | No common parameter space |
| Distill all six roles into one 3 GB model with no quality loss | Roles are LLM + T2I + T2V + depth + SAM + flow; not one student |
| INT4 is free on Apple Silicon | no autoawq/bitsandbytes on MPS |

### Generalization

Any compiled ML pipeline that is a union of specialists (not one monolith) should account disk as a working set over roles, not as the catalog sum. The same `E[disk]` law applies to cloud worker images with a shared cache volume.

---

## Architecture (what to build)

```
ShotList → builder.build() → RfirGraph
                ↓
     required_roles(graph)     # already known
                ↓
     ensure_roles(roles)       # fetch misses, demand-priority
                ↓
     run_graph(...)            # existing executor
                ↓
     disk LRU touch/evict      # after job, never evict PIN_ROLES
```

New files:

| File | Responsibility |
|---|---|
| `app/rfir/models/residency.py` | Math + role mapping (this PR) |
| `app/rfir/models/fetcher.py` | `ensure_roles` via `snapshot_download(allow_patterns=...)` (next) |
| `app/rfir/models/disk_lru.py` | Pin + LRU eviction of role directories (next) |

Keep: `registry.py` as the catalog, `loader.py` as VRAM load/unload, `precision.py` as dtype policy.

Packs:

| Pack | Roles | When |
|---|---|---|
| `core` | plan, depth, rife, nsfw | install / first worker start |
| `t2i` | one of FLUX or SDXL, never both unless env opt-in | first Tier A/B job |
| `t2v` | CogVideoX (or later Wan) + shared VAE | first Tier C/D job |
| `sam` | sam2-hiera-tiny | first Tier C job |

Env:

- `RENDERFLOW_RFIR_T2I_MODEL` already selects T2I. Fetcher must honor it and **not** download the other.
- `RENDERFLOW_MODELS_MAX_BYTES` optional cap; LRU evicts unpinned roles until under cap.
- `RENDERFLOW_RFIR_PREFETCH=0` default: no popcorn prefetch. Later optional.

### Quality / performance promise

Phase 1 does not change a single forward pass. It changes **which bytes exist on disk**. Capability and latency after a role is local are identical to today.

Phase 2 may change CUDA latency **down** (SVDQuant/Nunchaku). Quality must be measured; do not flip the default until the eval gate passes.

### Out of scope for the first implementation slice

- Training a MoE or chimera
- Random diffusion timestep queues
- Hypernetworks that generate weights
- Replacing the Vulkan compositor
