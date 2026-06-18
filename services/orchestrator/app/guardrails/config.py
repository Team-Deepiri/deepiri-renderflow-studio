"""Build a RenderFlowPolicy from project DB settings + env vars.

Spec reference: guardrails-implementation.md §17 (Configuration)
"""
from __future__ import annotations

import logging
import os
from typing import Any
from uuid import UUID

from app import db_repos
from app.guardrails.presets import RenderFlowPolicy, build_policy

logger = logging.getLogger(__name__)


def policy_for_project(
    project_id: UUID,
    user_id: str | None = None,
    user_role: str = "editor",
) -> RenderFlowPolicy:
    """Build a RenderFlowPolicy by merging env defaults -> preset -> project DB settings."""
    preset = _env_preset()
    enabled = _check_enabled()

    project = db_repos.fetch_project(project_id)
    overrides: dict[str, Any] = {
        "enabled": enabled,
        "user_id": user_id,
        "project_id": str(project_id),
        "user_role": user_role,
    }

    if project:
        overrides["ai_enabled"] = project.get("ai_enabled", True)
        ai_settings = (project.get("settings_jsonb") or {}).get("ai", {})
        _merge_ai_settings(ai_settings, overrides)

    _merge_env_overrides(overrides)

    return build_policy(preset, **overrides)


def _check_enabled() -> bool:
    """Enforce production safety rule: guardrails can only be disabled in dev mode."""
    enabled = os.environ.get("RENDERFLOW_GUARDRAILS_ENABLED", "true").lower() == "true"
    if not enabled:
        mode = os.environ.get("READINESS_MODE", "dev").strip().lower()
        if mode != "dev":
            logger.critical(
                "RENDERFLOW_GUARDRAILS_ENABLED=false is not allowed in READINESS_MODE=%s; forcing enabled",
                mode,
            )
            return True
        logger.warning("Guardrails disabled (READINESS_MODE=dev)")
    return enabled


def _env_preset() -> str:
    mode = os.environ.get("READINESS_MODE", "dev").strip().lower()
    if mode == "dev":
        return "dev"
    return os.environ.get("RENDERFLOW_GUARDRAIL_PRESET", "us_default")


def _merge_ai_settings(ai: dict, out: dict) -> None:
    field_map = {
        "enabled": "ai_enabled",
        "allowed_modes": "allowed_modes",
        "max_tier": "max_tier",
        "max_duration_sec": "max_duration_sec",
        "cloud_allowed": "cloud_allowed",
        "local_only": "local_only",
        "require_review": "require_review",
        "nsfw_mode": "nsfw_mode",
        "likeness_mode": "likeness_mode",
        "copyright_mode": "copyright_mode",
        "region_policy": "region_policy",
        "csam_hash_check": "csam_hash_check",
    }
    for src_key, dst_key in field_map.items():
        if src_key in ai:
            out[dst_key] = ai[src_key]


def _merge_env_overrides(out: dict) -> None:
    env_map = {
        "RENDERFLOW_GUARDRAIL_NSFW_MODE": "nsfw_mode",
        "RENDERFLOW_GUARDRAIL_RATE_LIMIT": "rate_limit_per_hour",
        "RENDERFLOW_GUARDRAIL_PROVENANCE": "provenance_mode",
        "RENDERFLOW_GUARDRAIL_CSAM_HASH": "csam_hash_check",
    }
    for env_key, field in env_map.items():
        val = os.environ.get(env_key)
        if val is not None:
            if field == "rate_limit_per_hour":
                out[field] = int(val.split("/")[0])
            elif field == "csam_hash_check":
                out[field] = val.lower() == "true"
            else:
                out[field] = val
