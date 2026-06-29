"""RFIR Checkpointing — serialize/resume at shot boundaries for spot GPU survival.

Saves enough state at each shot boundary so a preempted worker can resume
from the next unfinished shot rather than restarting the entire job.

Checkpoint contents (per design doc §5.8):
  - shot_index: index of the last completed shot
  - spent_gpu_seconds: cumulative GPU time so far
  - node_cursor: index into the execution order
  - artifacts: map of artifact keys → URIs produced so far
  - tier_distribution: effective tier mix for metrics continuity
  - downgrades: budget downgrades recorded so far

Storage: local file (file:// URI) or S3 (s3:// URI).

Spec reference: rfir-inference-engine-implementation.md §4.2
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class Checkpoint:
    job_id: str
    shot_index: int
    spent_gpu_seconds: float
    node_cursor: int
    artifacts: dict[str, str] = field(default_factory=dict)
    tier_distribution: dict[str, int] = field(default_factory=dict)
    downgrades: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Checkpoint:
        return cls(
            job_id=data["job_id"],
            shot_index=data["shot_index"],
            spent_gpu_seconds=data["spent_gpu_seconds"],
            node_cursor=data["node_cursor"],
            artifacts=data.get("artifacts", {}),
            tier_distribution=data.get("tier_distribution", {}),
            downgrades=data.get("downgrades", []),
        )


def save(checkpoint: Checkpoint, uri: str) -> str:
    """Save a checkpoint to a local file or S3 URI. Returns the URI."""
    data = json.dumps(checkpoint.to_dict(), indent=2)

    if uri.startswith("s3://"):
        return _save_s3(data, uri)

    path = _uri_to_path(uri)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data, encoding="utf-8")
    logger.info("checkpoint saved: %s (shot %d, %.1fs GPU)",
                uri, checkpoint.shot_index, checkpoint.spent_gpu_seconds)
    return uri


def load(uri: str) -> Checkpoint | None:
    """Load a checkpoint from a local file or S3 URI. Returns None if not found."""
    try:
        if uri.startswith("s3://"):
            return _load_s3(uri)

        path = _uri_to_path(uri)
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        cp = Checkpoint.from_dict(data)
        logger.info("checkpoint loaded: %s (shot %d, %.1fs GPU)",
                    uri, cp.shot_index, cp.spent_gpu_seconds)
        return cp
    except Exception as e:
        logger.warning("failed to load checkpoint %s: %s", uri, e)
        return None


def delete(uri: str) -> None:
    """Remove a checkpoint after job completion."""
    try:
        if uri.startswith("s3://"):
            _delete_s3(uri)
            return
        path = _uri_to_path(uri)
        if path.exists():
            path.unlink()
            logger.info("checkpoint deleted: %s", uri)
    except Exception as e:
        logger.warning("failed to delete checkpoint %s: %s", uri, e)


def checkpoint_uri(job_id: str, base_dir: str | None = None) -> str:
    """Build the canonical checkpoint URI for a job."""
    base = base_dir or os.environ.get("RENDERFLOW_CHECKPOINT_DIR", "")
    if base.startswith("s3://"):
        return f"{base.rstrip('/')}/{job_id}/checkpoint.json"
    local_dir = base or "/tmp/rfir-checkpoints"
    return f"file://{local_dir}/{job_id}/checkpoint.json"


def _uri_to_path(uri: str) -> Path:
    if uri.startswith("file://"):
        return Path(uri[7:])
    return Path(uri)


# ---------------------------------------------------------------------------
# S3 stubs — wired when infra/docker MinIO or AWS is available
# ---------------------------------------------------------------------------

def _save_s3(data: str, uri: str) -> str:
    logger.warning("S3 checkpoint save not yet implemented: %s", uri)
    return uri


def _load_s3(uri: str) -> Checkpoint | None:
    logger.warning("S3 checkpoint load not yet implemented: %s", uri)
    return None


def _delete_s3(uri: str) -> None:
    logger.warning("S3 checkpoint delete not yet implemented: %s", uri)
