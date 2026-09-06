"""Fetch the model roles a compiled graph needs, and nothing else.

The compiler knows `required_roles(graph)` before any GPU work, so covering
disk is a demand problem, not a guess. Roles already resident are skipped;
missing ones are popped biggest-first, because the largest download blocks
the GPU longest.

This module must not import torch — it runs before any model is loaded.

Spec: docs/superpowers/specs/2026-08-21-rfir-role-residency-design.md
"""
from __future__ import annotations

import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.rfir.models.registry import REGISTRY, ModelManifest, artifacts_for_roles
from app.rfir.models.residency import (
    ROLE_BYTES_FP16,
    FetchItem,
    catalog_bytes_fp16,
    fetch_priority,
)

logger = logging.getLogger(__name__)

DownloadFn = Callable[..., str]

# Download groups for scripts/download_rfir_models.py. "all" is explicit —
# the default is core + one T2I, never the full catalog.
PACKS: tuple[str, ...] = ("core", "t2i", "t2v", "sam")
DEFAULT_PACKS: tuple[str, ...] = ("core", "t2i")


def packs_to_roles(packs: list[str] | tuple[str, ...]) -> frozenset[str]:
    """Roles covered by the named packs. `all` means every registered pack."""
    wanted = set(packs)
    if "all" in wanted:
        wanted.discard("all")
        wanted.update(PACKS)
    unknown = wanted - set(PACKS)
    if unknown:
        raise ValueError(f"unknown pack(s): {sorted(unknown)}; known: {list(PACKS)}")
    return frozenset(m.role for m in REGISTRY.values() if m.pack in wanted)


@dataclass(frozen=True)
class ResidencyReport:
    """What this job found on disk, and what it had to pay for.

    `rho_hat` is the measured counterpart to the design's ρ = E[disk] / catalog:
    the share of the old prepaid catalog this job actually needed resident. A
    Tier A job should sit well below 1.0 — that gap is the whole point.
    """

    hot_roles: frozenset[str]
    missing_roles: frozenset[str]
    hot_bytes: int
    miss_bytes: int
    rho_hat: float


def residency_report(
    roles: frozenset[str], *, models_dir: str, t2i_model_id: str
) -> ResidencyReport:
    """Classify a job's roles as hot or missing, before any fetch happens.

    Sizes come from the fp16 table rather than `du`, so a hit and a miss are
    comparable across machines and the numbers line up with the design's
    predictions instead of with local quantization choices.
    """
    hot: set[str] = set()
    missing: set[str] = set()
    for manifest in artifacts_for_roles(roles, t2i_model_id=t2i_model_id):
        if is_resident(models_dir, manifest.local_dir):
            hot.add(manifest.role)
        elif manifest.repo:
            missing.add(manifest.role)

    hot_bytes = sum(ROLE_BYTES_FP16.get(r, 0) for r in hot)
    catalog = catalog_bytes_fp16(False)
    return ResidencyReport(
        hot_roles=frozenset(hot),
        missing_roles=frozenset(missing),
        hot_bytes=hot_bytes,
        miss_bytes=sum(ROLE_BYTES_FP16.get(r, 0) for r in missing),
        rho_hat=hot_bytes / catalog if catalog else 0.0,
    )


def plan_downloads(
    packs: list[str] | tuple[str, ...], *, t2i_model_id: str
) -> list[ModelManifest]:
    """Artifacts the bootstrap script should pull for `packs`, biggest first.

    Same covering rules as a live job — one T2I backend, shared checkpoints
    fetched once — so a pre-fetch and an on-demand fetch never disagree about
    what belongs on disk. Roles with no HF repo (in-repo LFS weights) are
    omitted: there is nothing to snapshot.
    """
    manifests = artifacts_for_roles(packs_to_roles(packs), t2i_model_id=t2i_model_id)
    by_role = {m.role: m for m in manifests if m.repo}
    order = fetch_priority(
        [
            FetchItem(role=role, bytes=ROLE_BYTES_FP16.get(role, 0), in_current_job=True)
            for role in by_role
        ]
    )
    return [by_role[item.role] for item in order]


def all_role_dirs(t2i_model_id: str) -> dict[str, str]:
    """Every registered role → the directory it occupies, for the LRU.

    The T2I backend that is *not* selected appears under the synthetic role
    `t2i_keyframe_fallback` (the same key `ROLE_BYTES_FP16` uses). That role is
    unpinned, so an SDXL directory left behind by an older prepaid install is
    reclaimable instead of sitting on disk forever.
    """
    dirs: dict[str, str] = {}
    for manifest in REGISTRY.values():
        if manifest.role == "t2i_keyframe" and manifest.id != t2i_model_id:
            dirs.setdefault("t2i_keyframe_fallback", manifest.local_dir)
            continue
        dirs.setdefault(manifest.role, manifest.local_dir)
    return dirs


# Extensions that carry actual weights. A snapshot that pulled only README.md,
# .gitattributes and cache metadata is a failed download wearing a directory.
WEIGHT_SUFFIXES: frozenset[str] = frozenset(
    {".safetensors", ".bin", ".gguf", ".pth", ".pt", ".ckpt", ".pkl", ".onnx", ".msgpack"}
)


def is_resident(models_dir: str, local_dir: str) -> bool:
    """A role is resident iff its dir holds at least one weights file.

    "Exists and is non-empty" is not enough. A gated repo (FLUX without an
    accepted licence) still writes README.md and .gitattributes before the 401,
    leaving a ~16 KB directory that looks populated. Treating that as resident
    makes the fetcher skip the download and hands the loader a model that is
    not there — the exact failure this module exists to prevent.

    Weights may sit in subdirectories (diffusers keeps them under transformer/,
    vae/, text_encoder/), so this walks the tree.
    """
    path = os.path.join(models_dir, local_dir)
    if not os.path.isdir(path):
        return False
    for root, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if not d.startswith(".")]  # skip .cache/huggingface
        for name in files:
            if os.path.splitext(name)[1].lower() in WEIGHT_SUFFIXES:
                return True
    return False


def _snapshot_download(repo_id: str, local_dir: str, allow_patterns: Any = None) -> str:
    from huggingface_hub import snapshot_download

    return snapshot_download(
        repo_id=repo_id, local_dir=local_dir, allow_patterns=allow_patterns
    )


def ensure_roles(
    roles: frozenset[str],
    *,
    models_dir: str,
    t2i_model_id: str,
    download: DownloadFn | None = None,
) -> list[str]:
    """Make every role in `roles` resident under `models_dir`.

    Returns the local_dir names that exist afterwards, resident and freshly
    fetched alike. Raises RuntimeError if a fetch fails or lands incomplete —
    the executor must not start a graph whose weights are half-written.
    """
    fetch = download or _snapshot_download
    manifests = artifacts_for_roles(roles, t2i_model_id=t2i_model_id)

    resident: list[str] = []
    missing: dict[str, ModelManifest] = {}
    for manifest in manifests:
        if is_resident(models_dir, manifest.local_dir):
            resident.append(manifest.local_dir)
        elif not manifest.repo:
            # In-repo LFS weights (RIFE). Nothing to snapshot; the loader
            # resolves these from the source tree and raises if absent.
            logger.debug("role %s has no HF repo; skipping fetch", manifest.role)
        else:
            missing[manifest.role] = manifest

    queue = [
        FetchItem(
            role=role,
            bytes=ROLE_BYTES_FP16.get(role, 0),
            in_current_job=True,
        )
        for role in missing
    ]

    fetched: list[str] = []
    for item in fetch_priority(queue):
        manifest = missing[item.role]
        dest = os.path.join(models_dir, manifest.local_dir)
        logger.info(
            "fetching role=%s repo=%s (~%.1f GB)",
            manifest.role,
            manifest.repo,
            item.bytes / 1e9,
        )
        try:
            fetch(
                manifest.repo,
                dest,
                list(manifest.allow_patterns) if manifest.allow_patterns else None,
            )
        except Exception as exc:  # noqa: BLE001 — re-raised with the role attached
            raise RuntimeError(
                f"fetch failed for role {item.role!r} ({manifest.repo} → {dest}): {exc}"
            ) from exc
        if not is_resident(models_dir, manifest.local_dir):
            raise RuntimeError(
                f"fetch for role {item.role!r} left {manifest.local_dir!r} empty "
                f"({manifest.repo}). Gated repo? Run: huggingface-cli login"
            )
        fetched.append(manifest.local_dir)

    return resident + fetched
