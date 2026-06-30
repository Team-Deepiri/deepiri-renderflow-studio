"""Tests for the RFIR desktop preview endpoint (§5.5).

`app.rfir` lives in services/model-workers, a separate Poetry project with
no path dependency from the orchestrator and a colliding top-level package
name (`app`). Until that's resolved, the endpoint must degrade to a clean
503 rather than a raw ImportError/500 — that contract is what's tested here.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.api.routers.rfir_preview import PreviewRequest, preview_tier_a


def test_preview_returns_503_when_rfir_module_unavailable():
    with pytest.raises(HTTPException) as exc_info:
        preview_tier_a(PreviewRequest(prompt="a calm lake at sunrise"))

    assert exc_info.value.status_code == 503
    assert "RFIR module not available" in exc_info.value.detail


def test_preview_request_defaults():
    req = PreviewRequest(prompt="test prompt")
    assert req.duration_sec == 5.0


def test_preview_request_custom_duration():
    req = PreviewRequest(prompt="test prompt", duration_sec=3.5)
    assert req.duration_sec == 3.5
