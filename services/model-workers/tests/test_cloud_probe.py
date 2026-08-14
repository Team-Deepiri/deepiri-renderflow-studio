"""Tests for cloud heartbeat → default max_tier / cloud_allowed."""
from __future__ import annotations

import pytest

from app.cloud_probe import (
    get_cloud_defaults,
    probe_cloud_defaults,
    reset_cloud_defaults_cache,
)


@pytest.fixture(autouse=True)
def _clear_probe_cache():
    reset_cloud_defaults_cache()
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


def test_probe_without_heartbeat_defaults_to_b(monkeypatch):
    monkeypatch.delenv("RENDERFLOW_RFIR_MAX_TIER", raising=False)
    monkeypatch.delenv("RENDERFLOW_CLOUD_ALLOWED", raising=False)

    d = probe_cloud_defaults(FakeRedis(heartbeat=False))
    assert d.cloud_reachable is False
    assert d.max_tier == "B"
    assert d.cloud_allowed is False
    assert get_cloud_defaults() == d


def test_probe_with_heartbeat_defaults_to_c(monkeypatch):
    monkeypatch.delenv("RENDERFLOW_RFIR_MAX_TIER", raising=False)
    monkeypatch.delenv("RENDERFLOW_CLOUD_ALLOWED", raising=False)

    d = probe_cloud_defaults(FakeRedis(heartbeat=True))
    assert d.cloud_reachable is True
    assert d.max_tier == "C"
    assert d.cloud_allowed is True


def test_env_overrides_probe(monkeypatch):
    monkeypatch.setenv("RENDERFLOW_RFIR_MAX_TIER", "C")
    monkeypatch.setenv("RENDERFLOW_CLOUD_ALLOWED", "true")

    d = probe_cloud_defaults(FakeRedis(heartbeat=False))
    assert d.cloud_reachable is False
    assert d.max_tier == "C"
    assert d.cloud_allowed is True


def test_unprobed_cache_is_safe_local():
    d = get_cloud_defaults()
    assert d.max_tier == "B"
    assert d.cloud_allowed is False
