"""Tests for local ArtifactStore (no network / no secrets)."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.artifact_store import LocalArtifactStore, NullArtifactStore, get_artifact_store


def test_null_store_healthcheck_false():
    s = NullArtifactStore()
    assert s.healthcheck() is False


def test_get_artifact_store_defaults_to_null(monkeypatch):
    monkeypatch.delenv("RENDERFLOW_ARTIFACT_STORE", raising=False)
    monkeypatch.delenv("RENDERFLOW_ARTIFACT_ROOT", raising=False)
    store = get_artifact_store()
    assert store.healthcheck() is False


def test_local_put_get_roundtrip(tmp_path, monkeypatch):
    root = tmp_path / "artifacts"
    monkeypatch.setenv("RENDERFLOW_ARTIFACT_STORE", "local")
    monkeypatch.setenv("RENDERFLOW_ARTIFACT_ROOT", str(root))

    store = get_artifact_store()
    assert store.healthcheck() is True

    src = tmp_path / "src.pt"
    src.write_bytes(b"latent-bytes")
    uri = store.put("job-1/s1_t2v.pt", src)
    assert uri == "local:job-1/s1_t2v.pt"
    assert (root / "job-1" / "s1_t2v.pt").read_bytes() == b"latent-bytes"

    dest = tmp_path / "out.pt"
    store.get(uri, dest)
    assert dest.read_bytes() == b"latent-bytes"


def test_local_healthcheck_fails_without_root(monkeypatch):
    monkeypatch.setenv("RENDERFLOW_ARTIFACT_STORE", "local")
    monkeypatch.setenv("RENDERFLOW_ARTIFACT_ROOT", "")
    assert LocalArtifactStore("").healthcheck() is False


def test_gdrive_healthcheck_fails_without_creds(monkeypatch):
    monkeypatch.setenv("RENDERFLOW_ARTIFACT_STORE", "gdrive")
    monkeypatch.setenv("RENDERFLOW_ARTIFACT_ROOT", "folderid123")
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
    store = get_artifact_store()
    assert store.healthcheck() is False
