"""Tests for RFIR checkpointing — save/load/delete at shot boundaries (§4.2)."""
import json
import tempfile
from pathlib import Path

import pytest

from app.rfir.checkpoint import Checkpoint, save, load, delete, checkpoint_uri


def _sample_checkpoint() -> Checkpoint:
    return Checkpoint(
        job_id="test-job-123",
        shot_index=2,
        spent_gpu_seconds=14.5,
        node_cursor=8,
        artifacts={"s0_t2i": "/out/s0_t2i.png", "s1_rife_0": "/out/s1_rife_0.png"},
        tier_distribution={"A": 2, "B": 1},
        downgrades=[{"node_id": "s1_t2i", "op": "t2i_keyframe", "trigger": "gpu_time",
                     "reason": "downgraded_to_fit", "before_ms": 800, "after_ms": 400}],
    )


# ---------------------------------------------------------------------------
# Serialization roundtrip
# ---------------------------------------------------------------------------

def test_to_dict_and_from_dict():
    cp = _sample_checkpoint()
    d = cp.to_dict()
    restored = Checkpoint.from_dict(d)
    assert restored.job_id == cp.job_id
    assert restored.shot_index == cp.shot_index
    assert restored.spent_gpu_seconds == cp.spent_gpu_seconds
    assert restored.node_cursor == cp.node_cursor
    assert restored.artifacts == cp.artifacts
    assert restored.tier_distribution == cp.tier_distribution
    assert restored.downgrades == cp.downgrades


def test_to_dict_is_json_serializable():
    cp = _sample_checkpoint()
    raw = json.dumps(cp.to_dict())
    assert isinstance(raw, str)
    parsed = json.loads(raw)
    assert parsed["job_id"] == "test-job-123"


# ---------------------------------------------------------------------------
# File save / load / delete
# ---------------------------------------------------------------------------

def test_save_and_load_local():
    with tempfile.TemporaryDirectory() as tmpdir:
        uri = f"file://{tmpdir}/job1/checkpoint.json"
        cp = _sample_checkpoint()
        save(cp, uri)

        loaded = load(uri)
        assert loaded is not None
        assert loaded.job_id == cp.job_id
        assert loaded.shot_index == 2
        assert loaded.spent_gpu_seconds == 14.5
        assert loaded.node_cursor == 8
        assert loaded.artifacts == cp.artifacts


def test_load_nonexistent_returns_none():
    loaded = load("file:///nonexistent/path/checkpoint.json")
    assert loaded is None


def test_delete_removes_file():
    with tempfile.TemporaryDirectory() as tmpdir:
        uri = f"file://{tmpdir}/job1/checkpoint.json"
        save(_sample_checkpoint(), uri)
        assert load(uri) is not None

        delete(uri)
        assert load(uri) is None


def test_delete_nonexistent_no_error():
    delete("file:///nonexistent/checkpoint.json")


# ---------------------------------------------------------------------------
# URI builder
# ---------------------------------------------------------------------------

def test_checkpoint_uri_local():
    uri = checkpoint_uri("job-abc", base_dir="/tmp/rfir")
    assert uri == "file:///tmp/rfir/job-abc/checkpoint.json"


def test_checkpoint_uri_s3():
    uri = checkpoint_uri("job-abc", base_dir="s3://bucket/checkpoints")
    assert uri == "s3://bucket/checkpoints/job-abc/checkpoint.json"


def test_checkpoint_uri_default():
    uri = checkpoint_uri("job-abc")
    assert "job-abc" in uri
    assert uri.endswith("checkpoint.json")


# ---------------------------------------------------------------------------
# Resume state
# ---------------------------------------------------------------------------

def test_checkpoint_preserves_resume_state():
    """Verify that a checkpoint carries enough state to resume correctly."""
    cp = Checkpoint(
        job_id="resume-test",
        shot_index=1,
        spent_gpu_seconds=5.0,
        node_cursor=4,
        artifacts={"s0_t2i": "/out/s0.png"},
        tier_distribution={"A": 1, "C": 1},
        downgrades=[],
    )
    with tempfile.TemporaryDirectory() as tmpdir:
        uri = f"file://{tmpdir}/resume/checkpoint.json"
        save(cp, uri)
        restored = load(uri)

        assert restored.node_cursor == 4
        assert restored.spent_gpu_seconds == 5.0
        assert restored.artifacts == {"s0_t2i": "/out/s0.png"}
