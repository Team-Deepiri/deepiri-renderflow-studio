"""Tests for the RFIR desktop preview endpoint (§5.5).

`app.rfir` now resolves through the bridge package (app/rfir/__init__.py),
so in a monorepo checkout the endpoint compiles a real Tier-A graph. When
the bridge can't locate the RFIR sources (standalone deployment), the
endpoint must still degrade to a clean 503 rather than a raw
ImportError/500 — both contracts are tested here.
"""
from __future__ import annotations

import sys

import pytest
from fastapi import HTTPException

from app.api.routers.rfir_preview import PreviewRequest, preview_tier_a


def test_preview_compiles_tier_a_graph():
    result = preview_tier_a(PreviewRequest(prompt="a calm lake at sunrise"))

    assert result["ok"] is True
    assert result["shot_count"] == 1
    assert result["total_duration_sec"] == 5.0


def test_preview_returns_503_when_rfir_module_unavailable(monkeypatch):
    # Simulate the bridge failing to resolve: an import of cfsv_pipeline
    # (and thus app.rfir.*) raises ImportError.
    monkeypatch.setitem(sys.modules, "app.media.cfsv_pipeline", None)

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
