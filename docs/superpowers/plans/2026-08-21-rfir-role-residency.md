# RFIR Role Residency Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop prepaid 30 GB model installs by fetching only the roles a compiled RFIR graph needs, with one canonical T2I, while leaving inference quality and speed unchanged for any role that is already on disk.

**Architecture:** `required_roles(graph)` is already known at compile time. A fetcher covers missing roles in demand-priority order. A disk LRU keeps a small pin set and evicts unused giants. Quantization and Wan swaps are later gated tasks — do not start them until the math tests and phase-1 fetch tests are green.

**Tech Stack:** existing model-workers Poetry project, `huggingface_hub.snapshot_download`, pytest, current `registry.py` / `loader.py` / `compiler.builder`.

## Global Constraints

- Target branch for PRs: `dev` (never `main`).
- Do not change a forward pass in phase 1 (no new distillation, no timestep shuffling, no chimera weights).
- Do not download both FLUX and SDXL-Turbo unless `RENDERFLOW_RFIR_T2I_MODEL` explicitly asks for the fallback and an operator also sets `RENDERFLOW_RFIR_KEEP_BOTH_T2I=1`.
- Never compute `θ_i − θ_j` across different architectures.
- MPS stays fp16; CUDA INT4 is phase 2 and needs an eval gate.
- Math tests must stay green: `cd services/model-workers && poetry run pytest tests/test_residency_math.py -v`

**Quan: run the math tests first. Do not start Tasks 2+ until that suite is green.**

```bash
cd services/model-workers
poetry install
poetry run pytest tests/test_residency_math.py -v
```

Expected: all tests PASS. If any fail, fix `residency.py` / the test — do not “work around” by implementing fetch.

---

### File map

| File | Role |
|------|------|
| `services/model-workers/app/rfir/models/residency.py` | Working-set math + op→role (this PR; do not rewrite the equations) |
| `services/model-workers/tests/test_residency_math.py` | Contract tests for the equations |
| `services/model-workers/app/rfir/models/fetcher.py` | `ensure_roles` / HuggingFace snapshot |
| `services/model-workers/app/rfir/models/disk_lru.py` | Pin + LRU on role directories |
| `services/model-workers/app/rfir/models/registry.py` | Add `local_dir`, `allow_patterns`, `pack` fields |
| `services/model-workers/app/rfir/executor/engine.py` | Call `ensure_roles` before walking nodes |
| `scripts/download_rfir_models.py` | Pack-aware download; default `core` + canonical T2I only |
| `services/model-workers/tests/test_bootstrap_env.py` | Stop requiring every giant to exist |
| `README.md` | Disk numbers and fetch behavior |

---

### Task 1: Confirm the math contract (no product code)

**Files:**
- Read: `app/rfir/models/residency.py`
- Read: `tests/test_residency_math.py`
- Read: `docs/superpowers/specs/2026-08-21-rfir-role-residency-design.md`

**Interfaces:**
- Consumes: nothing
- Produces: confidence that `required_roles`, `resident_probability`, `expected_disk_bytes`, `miss_bytes`, `fetch_priority`, `refuse_cross_architecture_residual` are the API later tasks must call

- [ ] **Step 1: Run the math tests**

```bash
cd services/model-workers
poetry run pytest tests/test_residency_math.py -v
```

Expected: PASS. Record the count of passed tests in the PR comment.

- [ ] **Step 2: Read the two failed guesses in the spec**

Confirm you will **not** implement random diffusion timestep order or cross-architecture LoRA. If a later idea needs either, it is a new spec, not this plan.

- [ ] **Step 3: Commit nothing unless a test was actually failing and you fixed a bug in the math**

If tests already pass, move to Task 2.

---

### Task 2: Map roles to registry artifacts

**Files:**
- Modify: `services/model-workers/app/rfir/models/registry.py`
- Create: `services/model-workers/tests/test_registry_packs.py`

**Interfaces:**
- Consumes: `ModelManifest` in `registry.py`
- Produces: `ModelManifest.pack: str`, `ModelManifest.local_dir: str`, `ModelManifest.allow_patterns: tuple[str, ...]`, `def artifacts_for_roles(roles: frozenset[str], t2i_model_id: str) -> list[ModelManifest]`

- [ ] **Step 1: Write the failing test**

```python
# services/model-workers/tests/test_registry_packs.py
from app.rfir.models.registry import artifacts_for_roles, get_manifest


def test_t2i_role_returns_only_canonical_flux():
    arts = artifacts_for_roles(frozenset({"t2i_keyframe"}), t2i_model_id="flux-schnell-fp16")
    ids = {a.id for a in arts}
    assert "flux-schnell-fp16" in ids
    assert "sdxl-turbo-fp16" not in ids


def test_t2i_role_can_select_sdxl_without_flux():
    arts = artifacts_for_roles(frozenset({"t2i_keyframe"}), t2i_model_id="sdxl-turbo-fp16")
    ids = {a.id for a in arts}
    assert "sdxl-turbo-fp16" in ids
    assert "flux-schnell-fp16" not in ids


def test_t2v_role_shares_vae_checkpoint():
    arts = artifacts_for_roles(frozenset({"sparse_t2v", "vae"}), t2i_model_id="flux-schnell-fp16")
    dirs = {a.local_dir for a in arts}
    assert "cogvideox-2b" in dirs
    assert len(dirs) == 1


def test_unknown_t2i_id_raises():
    import pytest
    with pytest.raises(ValueError, match="t2i"):
        artifacts_for_roles(frozenset({"t2i_keyframe"}), t2i_model_id="not-a-model")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd services/model-workers
poetry run pytest tests/test_registry_packs.py -v
```

Expected: FAIL with `ImportError` or `TypeError` (`artifacts_for_roles` missing / `ModelManifest` lacks fields).

- [ ] **Step 3: Write minimal implementation**

Add to `ModelManifest`:

```python
pack: str = "core"
local_dir: str = ""          # subdirectory under RENDERFLOW_MODELS_DIR
allow_patterns: tuple[str, ...] = ()
```

Set `local_dir` to match today’s loader paths (`flux-schnell`, `sdxl-turbo`, `cogvideox-2b`, …). Set Qwen `allow_patterns=("*q4_k_m.gguf",)` as today.

```python
def artifacts_for_roles(roles: frozenset[str], t2i_model_id: str) -> list[ModelManifest]:
    out: list[ModelManifest] = []
    seen_dirs: set[str] = set()
    for manifest in REGISTRY.values():
        if manifest.role == "t2i_keyframe" and "t2i_keyframe" in roles:
            if manifest.id != t2i_model_id:
                continue
        elif manifest.role not in roles:
            continue
        key = manifest.local_dir or manifest.id
        if key in seen_dirs:
            continue
        seen_dirs.add(key)
        out.append(manifest)
    if "t2i_keyframe" in roles and get_manifest(t2i_model_id) is None:
        raise ValueError(f"unknown t2i model: {t2i_model_id}")
    if "t2i_keyframe" in roles and not any(m.role == "t2i_keyframe" for m in out):
        raise ValueError(f"t2i model {t2i_model_id!r} is not a t2i_keyframe")
    return out
```

Fill `local_dir` on every existing `REGISTRY` entry. `cogvideox-2b` and `cogvideox-2b-vae` share `local_dir="cogvideox-2b"`.

- [ ] **Step 4: Run tests**

```bash
cd services/model-workers
poetry run pytest tests/test_registry_packs.py tests/test_residency_math.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add services/model-workers/app/rfir/models/registry.py services/model-workers/tests/test_registry_packs.py
git commit -m "$(cat <<'EOF'
feat(rfir): map graph roles to a single T2I artifact

Stop treating FLUX and SDXL as a prepaid pair; role covering picks one.
EOF
)"
```

---

### Task 3: Fetcher with demand-priority pop

**Files:**
- Create: `services/model-workers/app/rfir/models/fetcher.py`
- Create: `services/model-workers/tests/test_fetcher.py`

**Interfaces:**
- Consumes: `artifacts_for_roles`, `FetchItem`, `fetch_priority`, `miss_bytes` from residency
- Produces: `def ensure_roles(roles: frozenset[str], *, models_dir: str, t2i_model_id: str, download: Callable[..., str] | None = None) -> list[str]` returning local dirs that now exist

- [ ] **Step 1: Write the failing test** (no network)

```python
# services/model-workers/tests/test_fetcher.py
from pathlib import Path

from app.rfir.models.fetcher import ensure_roles
from app.rfir.models.residency import DEFAULT_T2I_MODEL_ID


def test_ensure_roles_skips_present_and_fetches_missing_in_priority_order(tmp_path, monkeypatch):
    models = tmp_path / "models"
    (models / "depth-anything-v2-small").mkdir(parents=True)
    (models / "depth-anything-v2-small" / "config.json").write_text("{}")
    calls: list[str] = []

    def fake_download(repo_id: str, local_dir: str, allow_patterns=None) -> str:
        calls.append(repo_id)
        Path(local_dir).mkdir(parents=True, exist_ok=True)
        (Path(local_dir) / "ok").write_text("1")
        return local_dir

    ensure_roles(
        frozenset({"t2i_keyframe", "depth_estimate"}),
        models_dir=str(models),
        t2i_model_id=DEFAULT_T2I_MODEL_ID,
        download=fake_download,
    )
    assert "black-forest-labs/FLUX.1-schnell" in calls
    assert "stabilityai/sdxl-turbo" not in calls
    # depth already on disk → not fetched
    assert all("Depth-Anything" not in c for c in calls)


def test_ensure_roles_does_not_fetch_t2v_for_tier_a(tmp_path):
    calls: list[str] = []

    def fake_download(repo_id: str, local_dir: str, allow_patterns=None) -> str:
        calls.append(repo_id)
        Path(local_dir).mkdir(parents=True, exist_ok=True)
        (Path(local_dir) / "ok").write_text("1")
        return local_dir

    ensure_roles(
        frozenset({"t2i_keyframe"}),
        models_dir=str(tmp_path),
        t2i_model_id=DEFAULT_T2I_MODEL_ID,
        download=fake_download,
    )
    assert all("CogVideoX" not in c and "cogvideox" not in c.lower() for c in calls)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd services/model-workers
poetry run pytest tests/test_fetcher.py -v
```

Expected: FAIL (`fetcher` module missing)

- [ ] **Step 3: Write minimal implementation**

`ensure_roles` must:

1. Resolve manifests via `artifacts_for_roles`.
2. Treat a dir as present iff it exists and is non-empty (same as bootstrap tests).
3. Build `FetchItem(role=..., bytes=ROLE_BYTES_FP16.get(role, 0), in_current_job=True)` for misses.
4. `fetch_priority(...)` then call `download(repo, dest, allow_patterns)` — default `download` wraps `huggingface_hub.snapshot_download`.
5. Pass `allow_patterns` from the manifest when non-empty.

Do not import torch.

- [ ] **Step 4: Run tests**

```bash
cd services/model-workers
poetry run pytest tests/test_fetcher.py tests/test_residency_math.py tests/test_registry_packs.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add services/model-workers/app/rfir/models/fetcher.py services/model-workers/tests/test_fetcher.py
git commit -m "$(cat <<'EOF'
feat(rfir): fetch missing roles in demand-priority order

Graph demand is known before GPU work; do not prepaid-pull T2V or the unused T2I.
EOF
)"
```

---

### Task 4: Disk LRU with pin set

**Files:**
- Create: `services/model-workers/app/rfir/models/disk_lru.py`
- Create: `services/model-workers/tests/test_disk_lru.py`

**Interfaces:**
- Consumes: `PIN_ROLES`, `ROLE_BYTES_FP16`
- Produces: `def touch(role: str, models_dir: str, clock: Callable[[], float] | None = None) -> None`, `def evict_until(models_dir: str, max_bytes: int, role_dirs: dict[str, str]) -> list[str]` returning evicted local_dir names. Never evicts a pin role.

- [ ] **Step 1: Write the failing test**

```python
# services/model-workers/tests/test_disk_lru.py
from pathlib import Path

from app.rfir.models.disk_lru import evict_until, touch
from app.rfir.models.residency import PIN_ROLES


def _plant(root: Path, name: str, nbytes: int) -> None:
    d = root / name
    d.mkdir(parents=True)
    (d / "w.bin").write_bytes(b"x" * nbytes)


def test_evict_drops_oldest_unpinned_not_pins(tmp_path):
    models = tmp_path / "models"
    _plant(models, "flux-schnell", 50)
    _plant(models, "cogvideox-2b", 50)
    _plant(models, "depth-anything-v2-small", 10)
    role_dirs = {
        "t2i_keyframe": "flux-schnell",
        "sparse_t2v": "cogvideox-2b",
        "depth_estimate": "depth-anything-v2-small",
    }
    touch("depth_estimate", str(models))
    touch("t2i_keyframe", str(models))
    touch("sparse_t2v", str(models))
    evicted = evict_until(str(models), max_bytes=70, role_dirs=role_dirs)
    assert "cogvideox-2b" in evicted or "flux-schnell" in evicted
    assert "depth-anything-v2-small" not in evicted
    assert "depth_estimate" in PIN_ROLES
```

- [ ] **Step 2: Run to see FAIL**

```bash
cd services/model-workers
poetry run pytest tests/test_disk_lru.py -v
```

- [ ] **Step 3: Implement**

Store last-used timestamps in `models_dir/.rfir-lru.json`. `evict_until` sums directory sizes, pops unpinned roles by oldest touch until `total <= max_bytes` or only pins remain. Deleting a role directory is allowed only if it is not in `PIN_ROLES`.

- [ ] **Step 4: Run tests + math suite**

```bash
cd services/model-workers
poetry run pytest tests/test_disk_lru.py tests/test_residency_math.py -v
```

- [ ] **Step 5: Commit**

```bash
git add services/model-workers/app/rfir/models/disk_lru.py services/model-workers/tests/test_disk_lru.py
git commit -m "$(cat <<'EOF'
feat(rfir): LRU-evict unpinned model dirs under a byte cap

Pins stay; T2V/T2I can leave disk so prepaid 30GB cannot come back.
EOF
)"
```

---

### Task 5: Wire fetch into the executor

**Files:**
- Modify: `services/model-workers/app/rfir/executor/engine.py` (`run_graph`)
- Modify: `services/model-workers/tests/test_redis_worker.py` if it mocks `load_model`
- Create: `services/model-workers/tests/test_engine_ensure_roles.py`

**Interfaces:**
- Consumes: `required_roles(graph)`, `ensure_roles(...)`
- Produces: `run_graph` calls `ensure_roles` once after handler registration and before the node loop

- [ ] **Step 1: Write the failing test**

```python
# services/model-workers/tests/test_engine_ensure_roles.py
from app.rfir.executor import engine
from app.rfir.ir.types import RfirGraph, RfirNode, InferenceBudget


def test_run_graph_ensures_roles_before_ops(monkeypatch, tmp_path):
    seen: dict[str, frozenset] = {}

    def fake_ensure(roles, **kwargs):
        seen["roles"] = roles
        return []

    monkeypatch.setattr("app.rfir.models.fetcher.ensure_roles", fake_ensure)
    monkeypatch.setattr(engine, "ensure_roles", fake_ensure)
    monkeypatch.setattr(engine, "detect_device", lambda: "cpu")
    monkeypatch.setattr(engine, "unload_all", lambda: None)

    # Avoid real ops: empty graph still muxes in production; use a graph with
    # only ffmpeg_mux and stub that handler after _register_handlers.
    graph = RfirGraph(nodes=[RfirNode(id="k", op="t2i_keyframe"), RfirNode(id="m", op="ffmpeg_mux")])
    monkeypatch.setenv("RENDERFLOW_MODELS_DIR", str(tmp_path))

    def boom(*args, **kwargs):
        raise RuntimeError("op should not run in this unit test")

    engine._OP_HANDLERS = {"t2i_keyframe": boom, "ffmpeg_mux": lambda *a, **k: None}
    try:
        engine.run_graph(graph, job_id="j1", output_dir=str(tmp_path / "out"), budget=InferenceBudget())
    except RuntimeError:
        pass
    assert "t2i_keyframe" in seen.get("roles", frozenset())
```

Adjust the stub so `ensure_roles` is invoked even if later ops fail. Prefer extracting a `_prepare_models(graph)` helper and testing that directly if `run_graph` is too heavy:

```python
def _prepare_models(graph: RfirGraph, models_dir: str, t2i_model_id: str) -> None:
    from app.rfir.models.fetcher import ensure_roles
    from app.rfir.models.residency import required_roles
    ensure_roles(required_roles(graph), models_dir=models_dir, t2i_model_id=t2i_model_id)
```

Test `_prepare_models` instead if that is cleaner. Do not download in tests.

- [ ] **Step 2: Run FAIL, then implement `_prepare_models` at the start of `run_graph`**

Read `t2i_model_id` from `os.environ.get("RENDERFLOW_RFIR_T2I_MODEL", DEFAULT_T2I_MODEL_ID)`.

After a successful job, `touch` each required role. If `RENDERFLOW_MODELS_MAX_BYTES` is set, call `evict_until`.

- [ ] **Step 3: Run**

```bash
cd services/model-workers
poetry run pytest tests/test_engine_ensure_roles.py tests/test_residency_math.py tests/test_redis_worker.py -v
```

- [ ] **Step 4: Commit**

```bash
git add services/model-workers/app/rfir/executor/engine.py services/model-workers/tests/test_engine_ensure_roles.py
git commit -m "$(cat <<'EOF'
feat(rfir): ensure graph roles on disk before executor runs

Compile-time demand drives fetch; the worker no longer assumes a 30GB tree.
EOF
)"
```

---

### Task 6: Pack-aware download script and bootstrap tests

**Files:**
- Modify: `scripts/download_rfir_models.py`
- Modify: `services/model-workers/tests/test_bootstrap_env.py`
- Modify: `README.md` (model weights section)

**Interfaces:**
- Consumes: `artifacts_for_roles`, packs `core|t2i|t2v|sam|all`
- Produces: CLI `--pack core,t2i` default (not `all`)

- [ ] **Step 1: Write a unit test for pack selection** (import the download module’s pack resolver; extract `def packs_to_roles(packs: list[str]) -> frozenset[str]` into `residency.py` or `fetcher.py` if the script is awkward to import)

```python
def test_default_packs_exclude_t2v_and_second_t2i():
    from app.rfir.models.fetcher import packs_to_roles
    roles = packs_to_roles(["core", "t2i"])
    assert "t2i_keyframe" in roles
    assert "sparse_t2v" not in roles
```

Default packs: `core` + `t2i`. `all` is explicit.

- [ ] **Step 2: Change `EXPECTED_DIRS` in `test_bootstrap_env.py`**

Only assert dirs for packs that are supposed to exist. Split:

- `test_core_and_t2i_present` — required when `RENDERFLOW_MODELS_DIR` is set for Tier A smoke.
- `test_t2v_optional` — skip if `cogvideox-2b` missing (no longer fail CI for a laptop without T2V).

- [ ] **Step 3: Update README model-weights bullet list**

State idle / Tier A / full-stack expected disk using the working-set law, and that first C/D job fetches T2V.

- [ ] **Step 4: Run**

```bash
cd services/model-workers
poetry run pytest tests/test_bootstrap_env.py tests/test_residency_math.py tests/test_registry_packs.py -v
```

- [ ] **Step 5: Commit**

```bash
git add scripts/download_rfir_models.py services/model-workers/tests/test_bootstrap_env.py README.md services/model-workers/app/rfir/models/fetcher.py
git commit -m "$(cat <<'EOF'
feat(rfir): default model download is core+T2I, not the 30GB catalog

T2V and the unused T2I backend stay off disk until a graph names them.
EOF
)"
```

---

### Task 7: Metrics

**Files:**
- Modify: `services/model-workers/app/rfir/metrics.py`
- Create: `services/model-workers/tests/test_residency_metrics.py`

**Interfaces:**
- Produces: counters/gauges `rfir_model_disk_bytes`, `rfir_model_fetch_bytes_total`, `rfir_model_hit_roles_total`, `rfir_model_miss_roles_total`

Log one JSON line per job: `{roles, hot_bytes, miss_bytes, rho_hat}` where `rho_hat = hot_bytes / catalog_bytes_fp16(False)`.

- [ ] Tests: increment miss when `ensure_roles` actually calls download; increment hit when dir already present.
- [ ] Commit `feat(rfir): export disk working-set metrics per job`

---

### Task 8 (phase 2, gated): CUDA INT4 disk artifacts

Do **not** start until Tasks 1–7 are merged and math+fetch tests are green.

Gate: 32 frozen prompts, 512×288, 4 steps, SSIM vs fp16 FLUX mean ≥ 0.90 **or** side-by-side review signed by Quan. MPS keeps fp16.

Use SVDQuant/Nunchaku (Li et al., ICLR 2025, arXiv:2411.05007) or the existing `autoawq` path in `precision.py` — ship **one** CUDA disk artifact, not fp16 plus INT4.

---

### Task 9 (phase 3, gated): Wan 2.1-T2V-1.3B bake-off

Do **not** start until phase 1 is in `dev`. Register `wan2.1-t2v-1.3b` as `sparse_t2v` candidate. Keep CogVideoX-2B as fallback. Flip default only after a frozen Tier C/D clip set matches or beats CogVideoX on motion + prompt adherence. This is a role swap, not a merge.

---

## Spec coverage

| Spec requirement | Task |
|---|---|
| Role-working-set law encoded and tested | 1 (done this PR) |
| One T2I artifact | 2, 3, 6 |
| Fetch by compiled graph | 3, 5 |
| Pin + LRU | 4, 5 |
| Download script packs | 6 |
| Metrics for E[disk] vs reality | 7 |
| SVDQuant same-arch INT4 | 8 (gated) |
| Wan swap | 9 (gated) |
| No chimera / no random ODE steps | Task 1 step 2 + `refuse_cross_architecture_residual` |

## Placeholder scan

None. Later phases are gated tasks with explicit entry conditions, not TBDs inside phase 1.
