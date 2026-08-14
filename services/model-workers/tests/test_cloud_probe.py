"""Tests for cloud heartbeat + artifact store → default max_tier / cloud_allowed."""
from __future__ import annotations

import pytest

from app.cloud_probe import (
    get_cloud_defaults,
    probe_cloud_defaults,
    reset_cloud_defaults_cache,
)


@pytest.fixture(autouse=True)
def _clear_probe_cache(monkeypatch):
    reset_cloud_defaults_cache()
    monkeypatch.delenv("RENDERFLOW_RFIR_MAX_TIER", raising=False)
    monkeypatch.delenv("RENDERFLOW_CLOUD_ALLOWED", raising=False)
    yield
    reset_cloud_defaults_cache()


class FakeRedis:
    def __init__(self, *, heartbeat: bool = False) -> None:
        self._heartbeat = heartbeat

    def exists(self, key: str) -> int:
        from renderflow_queue import REDIS_KEY_T2V_HEARTBEAT

        if key == REDIS_KEY_T2V_HEARTBEAT and self._heartbeat:
            return 1
        return 0


def _mock_store(monkeypatch, *, ok: bool):
    class _Store:
        def healthcheck(self) -> bool:
            return ok

    monkeypatch.setattr("app.cloud_probe.get_artifact_store", lambda: _Store())


def test_probe_without_heartbeat_defaults_to_b(monkeypatch):
    _mock_store(monkeypatch, ok=True)
    d = probe_cloud_defaults(FakeRedis(heartbeat=False))
    assert d.cloud_reachable is False
    assert d.storage_ok is True
    assert d.cloud_ready is False
    assert d.max_tier == "B"
    assert d.cloud_allowed is False


def test_probe_heartbeat_without_storage_defaults_to_b(monkeypatch):
    _mock_store(monkeypatch, ok=False)
    d = probe_cloud_defaults(FakeRedis(heartbeat=True))
    assert d.cloud_reachable is True
    assert d.storage_ok is False
    assert d.cloud_ready is False
    assert d.max_tier == "B"
    assert d.cloud_allowed is False


def test_probe_heartbeat_and_storage_defaults_to_c(monkeypatch):
    _mock_store(monkeypatch, ok=True)
    d = probe_cloud_defaults(FakeRedis(heartbeat=True))
    assert d.cloud_reachable is True
    assert d.storage_ok is True
    assert d.cloud_ready is True
    assert d.max_tier == "C"
    assert d.cloud_allowed is True
    assert get_cloud_defaults() == d


def test_env_overrides_probe(monkeypatch):
    _mock_store(monkeypatch, ok=False)
    monkeypatch.setenv("RENDERFLOW_RFIR_MAX_TIER", "C")
    monkeypatch.setenv("RENDERFLOW_CLOUD_ALLOWED", "true")

    d = probe_cloud_defaults(FakeRedis(heartbeat=False))
    assert d.cloud_ready is False
    assert d.max_tier == "C"
    assert d.cloud_allowed is True


def test_unprobed_cache_is_safe_local():
    d = get_cloud_defaults()
    assert d.max_tier == "B"
    assert d.cloud_allowed is False
    assert d.cloud_ready is False
