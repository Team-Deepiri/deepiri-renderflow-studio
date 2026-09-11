"""Disk LRU over role directories: pins stay, giants can leave.

Fetching on demand keeps the install small, but nothing shrinks a tree that
only ever grows. This is the other half: under a byte cap, evict the least
recently used *unpinned* role directories.

The pin set (`PIN_ROLES`) is small, used on nearly every job, and cheap to
keep — evicting it would just re-download it on the next graph. The giants
(FLUX, CogVideoX) are the ones worth reclaiming.

Last-use timestamps live in `<models_dir>/.rfir-lru.json`. A role with no
recorded use is treated as colder than any recorded one, so a directory that
predates this feature is a candidate rather than being pinned by accident.

Spec: docs/superpowers/specs/2026-08-21-rfir-role-residency-design.md
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import time
from collections.abc import Callable

from app.rfir.models.residency import PIN_ROLES

logger = logging.getLogger(__name__)

LRU_STATE_FILE = ".rfir-lru.json"


def _state_path(models_dir: str) -> str:
    return os.path.join(models_dir, LRU_STATE_FILE)


def _read_state(models_dir: str) -> dict[str, float]:
    """Role → last-use epoch seconds. A corrupt or absent file reads as empty."""
    try:
        with open(_state_path(models_dir), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): float(v) for k, v in data.items() if isinstance(v, (int, float))}


def touch(role: str, models_dir: str, *, clock: Callable[[], float] | None = None) -> None:
    """Record that `role` was just used. Never raises — this is bookkeeping."""
    now = (clock or time.time)()
    state = _read_state(models_dir)
    state[role] = now
    try:
        with open(_state_path(models_dir), "w", encoding="utf-8") as fh:
            json.dump(state, fh, indent=2, sort_keys=True)
    except OSError as exc:
        logger.debug("could not write LRU state in %s: %s", models_dir, exc)


def dir_bytes(path: str) -> int:
    """Total size of the files under `path`. Missing path is 0 bytes."""
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                continue
    return total


def resident_bytes(models_dir: str, role_dirs: dict[str, str]) -> int:
    """Bytes held by the role directories that are actually on disk."""
    seen: set[str] = set()
    total = 0
    for local_dir in role_dirs.values():
        if local_dir in seen:
            continue
        seen.add(local_dir)
        path = os.path.join(models_dir, local_dir)
        if os.path.isdir(path):
            total += dir_bytes(path)
    return total


def evict_until(
    models_dir: str,
    max_bytes: int,
    role_dirs: dict[str, str],
    pin: frozenset[str] = PIN_ROLES,
) -> list[str]:
    """Delete least-recently-used unpinned role dirs until under `max_bytes`.

    Returns the local_dir names removed, in eviction order. Stops early when
    only pinned roles remain, even if that leaves the tree over budget — the
    alternative is thrashing a model the next job needs anyway.
    """
    if max_bytes < 0:
        raise ValueError(f"max_bytes must be >= 0, got {max_bytes}")

    total = resident_bytes(models_dir, role_dirs)
    if total <= max_bytes:
        return []

    state = _read_state(models_dir)
    candidates: list[tuple[float, str, str]] = []
    seen: set[str] = set()
    for role, local_dir in role_dirs.items():
        if role in pin or local_dir in seen:
            continue
        path = os.path.join(models_dir, local_dir)
        if not os.path.isdir(path):
            continue
        seen.add(local_dir)
        # Never-touched sorts before every recorded timestamp.
        candidates.append((state.get(role, float("-inf")), role, local_dir))
    candidates.sort()

    evicted: list[str] = []
    for _last_used, role, local_dir in candidates:
        if total <= max_bytes:
            break
        path = os.path.join(models_dir, local_dir)
        freed = dir_bytes(path)
        try:
            shutil.rmtree(path)
        except OSError as exc:
            logger.warning("could not evict %s: %s", path, exc)
            continue
        total -= freed
        state.pop(role, None)
        evicted.append(local_dir)
        logger.info("evicted role=%s dir=%s freed=%.1f GB", role, local_dir, freed / 1e9)

    if evicted:
        try:
            with open(_state_path(models_dir), "w", encoding="utf-8") as fh:
                json.dump(state, fh, indent=2, sort_keys=True)
        except OSError as exc:
            logger.debug("could not write LRU state in %s: %s", models_dir, exc)

    return evicted
