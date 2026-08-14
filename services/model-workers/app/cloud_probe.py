"""Probe remote T2V cloud liveness and resolve default max_tier / cloud_allowed.

Used by model-workers at startup. Orchestrator is intentionally not involved.

Priority for each field:
  1. Explicit env override (if set)
  2. Live Redis heartbeat from a cloud T2V worker
  3. Safe local defaults (max_tier=B, cloud_allowed=False)
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

from renderflow_queue import t2v_cloud_reachable

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CloudDefaults:
    cloud_reachable: bool
    max_tier: str  # "B" or "C" (or env override A–D)
    cloud_allowed: bool


_cached: CloudDefaults | None = None


def probe_cloud_defaults(redis_client: Any | None = None) -> CloudDefaults:
    """Check heartbeat (if client given) and resolve defaults; cache the result."""
    global _cached

    reachable = False
    if redis_client is not None:
        try:
            reachable = bool(t2v_cloud_reachable(redis_client))
        except Exception as e:
            logger.warning("cloud T2V heartbeat probe failed: %s", e)
            reachable = False

    if "RENDERFLOW_RFIR_MAX_TIER" in os.environ:
        max_tier = os.environ["RENDERFLOW_RFIR_MAX_TIER"].strip().upper() or ("C" if reachable else "B")
    else:
        max_tier = "C" if reachable else "B"

    if "RENDERFLOW_CLOUD_ALLOWED" in os.environ:
        cloud_allowed = os.environ["RENDERFLOW_CLOUD_ALLOWED"].strip().lower() == "true"
    else:
        cloud_allowed = reachable

    defaults = CloudDefaults(
        cloud_reachable=reachable,
        max_tier=max_tier,
        cloud_allowed=cloud_allowed,
    )
    _cached = defaults
    logger.info(
        "cloud T2V probe: reachable=%s → default max_tier=%s cloud_allowed=%s",
        defaults.cloud_reachable,
        defaults.max_tier,
        defaults.cloud_allowed,
    )
    return defaults


def get_cloud_defaults() -> CloudDefaults:
    """Return last probe result, or safe local defaults if never probed."""
    if _cached is not None:
        return _cached
    return CloudDefaults(cloud_reachable=False, max_tier="B", cloud_allowed=False)


def reset_cloud_defaults_cache() -> None:
    """Test helper: clear the cached probe result."""
    global _cached
    _cached = None
