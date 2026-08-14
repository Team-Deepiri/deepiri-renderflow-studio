from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

REDIS_KEY_T2V_OPS = "renderflow:ops:t2v"
REDIS_KEY_T2V_RESULT_PREFIX = "renderflow:ops:t2v:result:"
REDIS_KEY_T2V_HEARTBEAT = "renderflow:ops:t2v:heartbeat"

# Default TTL for result keys (seconds). Local client should finish well before.
T2V_RESULT_TTL_SEC = 60 * 60  # 1 hour

# Cloud worker liveness: refreshed while the remote T2V process is running.
# Local model-workers treat a missing/expired key as "cloud not connected".
T2V_HEARTBEAT_TTL_SEC = 30

# Wan2.1 latent geometry (matches Diffusers WanPipeline defaults).
WAN_LATENT_CHANNELS = 16
WAN_SPATIAL_SCALE = 8
WAN_TEMPORAL_SCALE = 4


def t2v_result_key(op_id: str) -> str:
    """Redis key where the cloud worker publishes a ``T2VRemoteResult``."""
    return f"{REDIS_KEY_T2V_RESULT_PREFIX}{op_id}"


def touch_t2v_heartbeat(
    redis_client: Any,
    *,
    worker_id: str = "t2v",
    ttl_sec: int = T2V_HEARTBEAT_TTL_SEC,
) -> None:
    """Refresh the remote T2V worker liveness key (call periodically from cloud)."""
    redis_client.set(REDIS_KEY_T2V_HEARTBEAT, worker_id, ex=ttl_sec)


def t2v_cloud_reachable(redis_client: Any) -> bool:
    """True when a remote T2V worker has refreshed its heartbeat recently."""
    try:
        return bool(redis_client.exists(REDIS_KEY_T2V_HEARTBEAT))
    except Exception:
        return False


def expected_latent_shape(
    width: int,
    height: int,
    num_frames: int,
    *,
    channels: int = WAN_LATENT_CHANNELS,
    spatial_scale: int = WAN_SPATIAL_SCALE,
    temporal_scale: int = WAN_TEMPORAL_SCALE,
) -> list[int]:
    """Return ``[B, C, T, H', W']`` for a Wan-style video latent clip."""
    t = (num_frames - 1) // temporal_scale + 1
    h = height // spatial_scale
    w = width // spatial_scale
    return [1, channels, t, h, w]


def enqueue_t2v_request(redis_client: Any, request: T2VRemoteRequest) -> None:
    """RPUSH a request onto the remote T2V ops list."""
    redis_client.rpush(REDIS_KEY_T2V_OPS, request.to_json())


def publish_t2v_result(
    redis_client: Any,
    result: T2VRemoteResult,
    *,
    ttl_sec: int = T2V_RESULT_TTL_SEC,
) -> None:
    """Write result JSON to ``renderflow:ops:t2v:result:{op_id}`` with TTL."""
    redis_client.set(t2v_result_key(result.op_id), result.to_json(), ex=ttl_sec)


def wait_t2v_result(
    redis_client: Any,
    op_id: str,
    *,
    timeout_sec: float = 600.0,
    poll_interval_sec: float = 0.25,
) -> T2VRemoteResult:
    """Poll until a result appears for ``op_id`` or ``timeout_sec`` elapses."""
    import time

    key = t2v_result_key(op_id)
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        raw = redis_client.get(key)
        if raw:
            return T2VRemoteResult.from_json(raw)
        time.sleep(poll_interval_sec)
    raise TimeoutError(f"timed out waiting for T2V result op_id={op_id!r} after {timeout_sec}s")


class T2VRemoteStatus(str, Enum):
    OK = "ok"
    ERROR = "error"


@dataclass
class T2VRemoteRequest:

    job_id: str
    op_id: str
    prompt: str
    width: int
    height: int
    num_frames: int = 21
    steps: int = 12
    window_size: int = 17
    overlap: int = 4
    guidance_scale: float = 6.0
    full_frame: bool = False
    seed: int | None = None
    # Optional LTC prior: URI to a (1,C,T,H,W) or (1,C,H,W) latent tensor.
    init_latent_uri: str | None = None
    schema_version: int = 1

    def __post_init__(self) -> None:
        if not self.job_id:
            raise ValueError("job_id is required")
        if not self.op_id:
            raise ValueError("op_id is required")
        if not self.prompt:
            raise ValueError("prompt is required")
        if self.width <= 0 or self.height <= 0:
            raise ValueError("width and height must be positive")
        if self.width % 16 != 0 or self.height % 16 != 0:
            raise ValueError("width and height must be divisible by 16")
        if self.num_frames < 1:
            raise ValueError("num_frames must be >= 1")
        if self.steps < 1:
            raise ValueError("steps must be >= 1")
        if self.overlap < 0 or self.overlap >= self.window_size:
            raise ValueError("overlap must satisfy 0 <= overlap < window_size")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), separators=(",", ":"))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> T2VRemoteRequest:
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        filtered = {k: v for k, v in data.items() if k in known}
        return cls(**filtered)

    @classmethod
    def from_json(cls, raw: str | bytes) -> T2VRemoteRequest:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        return cls.from_dict(json.loads(raw))

@dataclass
class T2VRemoteResult:
    job_id: str
    op_id: str
    status: T2VRemoteStatus
    latent_uri: str | None = None
    latent_shape: list[int] = field(default_factory=list)
    dtype: str = "float16"
    error: str | None = None
    schema_version: int = 1

    def __post_init__(self) -> None:
        if isinstance(self.status, str):
            self.status = T2VRemoteStatus(self.status)
        if not self.job_id or not self.op_id:
            raise ValueError("job_id and op_id are required")
        if self.status == T2VRemoteStatus.OK:
            if not self.latent_uri:
                raise ValueError("latent_uri is required when status=ok")
            if len(self.latent_shape) != 5:
                raise ValueError("latent_shape must be 5D (B,C,T,H,W) when status=ok")
        if self.status == T2VRemoteStatus.ERROR and not self.error:
            raise ValueError("error is required when status=error")

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), separators=(",", ":"))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> T2VRemoteResult:
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        filtered = {k: v for k, v in data.items() if k in known}
        return cls(**filtered)

    @classmethod
    def from_json(cls, raw: str | bytes) -> T2VRemoteResult:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        return cls.from_dict(json.loads(raw))

    @classmethod
    def ok(
        cls,
        *,
        job_id: str,
        op_id: str,
        latent_uri: str,
        latent_shape: list[int],
        dtype: str = "float16",
    ) -> T2VRemoteResult:
        return cls(
            job_id=job_id,
            op_id=op_id,
            status=T2VRemoteStatus.OK,
            latent_uri=latent_uri,
            latent_shape=list(latent_shape),
            dtype=dtype,
        )

    @classmethod
    def fail(cls, *, job_id: str, op_id: str, error: str) -> T2VRemoteResult:
        return cls(
            job_id=job_id,
            op_id=op_id,
            status=T2VRemoteStatus.ERROR,
            error=error,
        )
