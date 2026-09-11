"""Model registry — manifest of available RFIR models.

Each entry declares: id, role, HuggingFace repo, quantization options,
VRAM requirements, and license. Models are verified by SHA256 on load.

Spec reference: rfir-inference-engine-implementation.md §1.1
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ModelManifest:
    """Static description of a registered model.

    `extras` is a free-form, per-model config bag read by that model's loader —
    keeps model-specific knobs out of the shared fields. Unknown keys are simply 
    ignored by loaders that don't use them.
    """

    id: str
    role: str
    repo: str = ""  # HF repo for auto-download; unused for in-repo weights (e.g. RIFE/LFS)
    quantization: str = "fp16"
    vram_mb: int = 0
    license: str = "unknown"
    sha256: str | None = None
    extras: dict = field(default_factory=dict)
    pack: str = "core"  # download group: core | t2i | t2v | sam
    local_dir: str = ""  # subdirectory under RENDERFLOW_MODELS_DIR
    allow_patterns: tuple[str, ...] = ()  # snapshot_download filter; () means whole repo


REGISTRY: dict[str, ModelManifest] = {
    "flux-schnell-fp16": ModelManifest(
        id="flux-schnell-fp16",
        role="t2i_keyframe",
        repo="black-forest-labs/FLUX.1-schnell",
        quantization="fp16",
        vram_mb=12288,
        license="apache-2.0",
        pack="t2i",
        local_dir="flux-schnell",
    ),
    "depth-anything-v2-small": ModelManifest(
        id="depth-anything-v2-small",
        role="depth_estimate",
        repo="depth-anything/Depth-Anything-V2-Small-hf",
        quantization="fp16",
        vram_mb=1024,
        license="apache-2.0",
        pack="core",
        local_dir="depth-anything-v2-small",
    ),
    "sdxl-turbo-fp16": ModelManifest(
        id="sdxl-turbo-fp16",
        role="t2i_keyframe",
        repo="stabilityai/sdxl-turbo",
        quantization="fp16",
        vram_mb=6144,
        license="openrail++",
        extras={"fallback_for": "flux-schnell-fp16"},
        pack="t2i",
        local_dir="sdxl-turbo",
    ),
    "rife-4.6": ModelManifest(
        id="rife-4.6",
        role="rife_interpolate",
        repo="", #weights are pointed by LFS, no HF repo exists
        quantization="fp16",
        vram_mb=2048,
        license="mit",
        extras={"filename": "flownet.pkl"},
        pack="core",
        local_dir="rife-4.6",  # in-repo LFS weights; the fetcher has no repo to pull
    ),
    "qwen2.5-3b-instruct-gguf": ModelManifest(
        id="qwen2.5-3b-instruct-gguf",
        role="plan_shots",
        repo="Qwen/Qwen2.5-3B-Instruct-GGUF",
        quantization="q4_k_m",
        vram_mb=2048,
        license="apache-2.0",
        extras={"filename": "*q4_k_m.gguf", "n_ctx": 4096},
        pack="core",
        local_dir="qwen2.5-3b-instruct-gguf",
        allow_patterns=("*q4_k_m.gguf",),  # one quant, not the whole multi-quant repo
    ),
    # --- Phase 3 models ---
    "sam2-hiera-tiny": ModelManifest(
        id="sam2-hiera-tiny",
        role="segment_subject",
        repo="facebook/sam2-hiera-tiny",
        quantization="fp16",
        vram_mb=1536,
        license="apache-2.0",
        pack="sam",
        local_dir="sam2-hiera-tiny",
    ),
    "cogvideox-2b": ModelManifest(
        id="cogvideox-2b",
        role="sparse_t2v",
        repo="THUDM/CogVideoX-2b",
        quantization="fp16",
        vram_mb=10240,
        license="apache-2.0",
        pack="t2v",
        local_dir="cogvideox-2b",
    ),
    "cogvideox-2b-vae": ModelManifest(
        id="cogvideox-2b-vae",
        role="vae",
        repo="THUDM/CogVideoX-2b",
        quantization="fp16",
        vram_mb=2048,
        license="apache-2.0",
        extras={"component": "vae"},
        pack="t2v",
        local_dir="cogvideox-2b",  # same snapshot as sparse_t2v — fetch once
    ),
    "nsfw-image-detection": ModelManifest(
        id="nsfw-image-detection",
        role="nsfw_classify",
        repo="Falconsai/nsfw_image_detection",
        quantization="fp16",
        vram_mb=512,
        license="apache-2.0",
        pack="core",
        local_dir="nsfw-image-detection",
    ),
}


def get_manifest(model_id: str) -> ModelManifest | None:
    return REGISTRY.get(model_id)


def list_models(role: str | None = None) -> list[ModelManifest]:
    if role:
        return [m for m in REGISTRY.values() if m.role == role]
    return list(REGISTRY.values())


def default_model_for_role(role: str) -> ModelManifest | None:
    models = list_models(role)
    return models[0] if models else None


def artifacts_for_roles(roles: frozenset[str], t2i_model_id: str) -> list[ModelManifest]:
    """Cover `roles` with the fewest disk artifacts.

    Two rules make this smaller than the prepaid catalog:

    * `t2i_keyframe` resolves to exactly one backend (`t2i_model_id`), never
      FLUX *and* SDXL-Turbo. Shipping both is the 6 GB of waste this PR removes.
    * Manifests that share a `local_dir` collapse to one entry, so `sparse_t2v`
      plus `vae` is one CogVideoX snapshot rather than two downloads.

    Roles with no registered model (ffmpeg / Vulkan ops) contribute nothing.
    Raises ValueError if `t2i_model_id` is unknown or is not a T2I backend.
    """
    if "t2i_keyframe" in roles:
        chosen = get_manifest(t2i_model_id)
        if chosen is None:
            raise ValueError(f"unknown t2i model: {t2i_model_id!r}")
        if chosen.role != "t2i_keyframe":
            raise ValueError(
                f"t2i model {t2i_model_id!r} is not a t2i_keyframe (role={chosen.role!r})"
            )

    out: list[ModelManifest] = []
    seen_dirs: set[str] = set()
    for manifest in REGISTRY.values():
        if manifest.role not in roles:
            continue
        if manifest.role == "t2i_keyframe" and manifest.id != t2i_model_id:
            continue
        key = manifest.local_dir or manifest.id
        if key in seen_dirs:
            continue
        seen_dirs.add(key)
        out.append(manifest)
    return out
