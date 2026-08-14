"""Tests for local ArtifactStore (no network / no secrets)."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.artifact_store import (
    LocalArtifactStore,
    NullArtifactStore,
    R2ArtifactStore,
    get_artifact_store,
)


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


class FakeR2Client:
    def __init__(self):
        self.objects: dict[tuple[str, str], bytes] = {}
        self.head_buckets: list[str] = []

    def head_bucket(self, *, Bucket: str):
        self.head_buckets.append(Bucket)

    def upload_file(self, source: str, bucket: str, key: str):
        self.objects[(bucket, key)] = Path(source).read_bytes()

    def download_file(self, bucket: str, key: str, destination: str):
        Path(destination).write_bytes(self.objects[(bucket, key)])


def test_r2_put_get_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("RENDERFLOW_R2_ENDPOINT", "https://account.r2.cloudflarestorage.com")
    monkeypatch.setenv("RENDERFLOW_R2_ACCESS_KEY_ID", "access-key")
    monkeypatch.setenv("RENDERFLOW_R2_SECRET_ACCESS_KEY", "secret-key")
    client = FakeR2Client()
    store = R2ArtifactStore("renderflow-t2v", client=client)

    assert store.healthcheck() is True
    assert client.head_buckets == ["renderflow-t2v"]

    source = tmp_path / "source.pt"
    source.write_bytes(b"latent-bytes")
    uri = store.put("job-1/s1_t2v.pt", source)
    assert uri == "r2:job-1/s1_t2v.pt"

    destination = tmp_path / "out.pt"
    store.get(uri, destination)
    assert destination.read_bytes() == b"latent-bytes"


def test_r2_healthcheck_fails_without_credentials(monkeypatch):
    monkeypatch.setenv("RENDERFLOW_ARTIFACT_STORE", "r2")
    monkeypatch.setenv("RENDERFLOW_ARTIFACT_ROOT", "renderflow-t2v")
    monkeypatch.delenv("RENDERFLOW_R2_ENDPOINT", raising=False)
    monkeypatch.delenv("RENDERFLOW_R2_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("RENDERFLOW_R2_SECRET_ACCESS_KEY", raising=False)
    assert get_artifact_store().healthcheck() is False
