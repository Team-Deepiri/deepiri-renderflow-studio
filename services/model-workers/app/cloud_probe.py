"""Probe remote T2V cloud liveness + shared artifact store; resolve defaults.

Used by model-workers at startup. Orchestrator is intentionally not involved.

Cloud Tier-C defaults require BOTH:
  1. Live Redis heartbeat from a cloud T2V worker
  2. Configured, healthy shared artifact store (RENDERFLOW_ARTIFACT_*)

If either check fails → default max_tier=B, cloud_allowed=False.

Priority for each field:
  1. Explicit env override (if set)
  2. Probe result (heartbeat ∧ storage)
  3. Safe local defaults (max_tier=B, cloud_allowed=False)

Secrets / folder ids / paths: env only — never hardcoded.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

from renderflow_queue import t2v_cloud_reachable

from app.artifact_store import get_artifact_store

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CloudDefaults:
    cloud_reachable: bool
    storage_ok: bool
    cloud_ready: bool
    max_tier: str  # "B" or "C" (or env override A–D)
    cloud_allowed: bool


_cached: CloudDefaults | None = None


def probe_cloud_defaults(redis_client: Any | None = None) -> CloudDefaults:
    """Check heartbeat + artifact store; resolve defaults; cache the result."""
    global _cached

    heartbeat_ok = False
    if redis_client is not None:
        try:
            heartbeat_ok = bool(t2v_cloud_reachable(redis_client))
        except Exception as e:
            logger.warning("cloud T2V heartbeat probe failed: %s", e)
            heartbeat_ok = False

    try:
        storage_ok = bool(get_artifact_store().healthcheck())
    except Exception as e:
        logger.warning("artifact store healthcheck failed: %s", e)
        storage_ok = False

    cloud_ready = heartbeat_ok and storage_ok

    if "RENDERFLOW_RFIR_MAX_TIER" in os.environ:
        max_tier = os.environ["RENDERFLOW_RFIR_MAX_TIER"].strip().upper() or (
            "C" if cloud_ready else "B"
        )
    else:
        max_tier = "C" if cloud_ready else "B"

    if "RENDERFLOW_CLOUD_ALLOWED" in os.environ:
        cloud_allowed = os.environ["RENDERFLOW_CLOUD_ALLOWED"].strip().lower() == "true"
    else:
        cloud_allowed = cloud_ready

    defaults = CloudDefaults(
        cloud_reachable=heartbeat_ok,
        storage_ok=storage_ok,
        cloud_ready=cloud_ready,
        max_tier=max_tier,
        cloud_allowed=cloud_allowed,
    )
    _cached = defaults
    logger.info(
        "cloud probe: heartbeat=%s storage=%s ready=%s → default max_tier=%s cloud_allowed=%s",
        defaults.cloud_reachable,
        defaults.storage_ok,
        defaults.cloud_ready,
        defaults.max_tier,
        defaults.cloud_allowed,
    )
    return defaults


def get_cloud_defaults() -> CloudDefaults:
    """Return last probe result, or safe local defaults if never probed."""
    if _cached is not None:
        return _cached
    return CloudDefaults(
        cloud_reachable=False,
        storage_ok=False,
        cloud_ready=False,
        max_tier="B",
        cloud_allowed=False,
    )


def reset_cloud_defaults_cache() -> None:
    """Test helper: clear the cached probe result."""
    global _cached
    _cached = None
