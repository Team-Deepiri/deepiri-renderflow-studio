"""Tests for the remote Wan T2V request/result contract."""
import json

import pytest

from renderflow_queue import (
    REDIS_KEY_T2V_OPS,
    T2VRemoteRequest,
    T2VRemoteResult,
    T2VRemoteStatus,
    expected_latent_shape,
    t2v_result_key,
)


def _valid_request(**overrides):
    base = dict(
        job_id="job-1",
        op_id="s1_t2v",
        prompt="hero runs",
        width=336,
        height=144,
    )
    base.update(overrides)
    return T2VRemoteRequest(**base)


def test_request_json_roundtrip():
    req = _valid_request(seed=7, steps=12)
    raw = req.to_json()
    back = T2VRemoteRequest.from_json(raw)
    assert back.job_id == "job-1"
    assert back.op_id == "s1_t2v"
    assert back.width == 336
    assert back.height == 144
    assert back.seed == 7
    assert back.schema_version == 1


def test_request_rejects_non_multiple_of_16():
    with pytest.raises(ValueError, match="divisible by 16"):
        _valid_request(width=335, height=144)


def test_request_rejects_bad_overlap():
    with pytest.raises(ValueError, match="overlap"):
        _valid_request(window_size=17, overlap=17)


def test_result_ok_factory_and_roundtrip():
    result = T2VRemoteResult.ok(
        job_id="job-1",
        op_id="s1_t2v",
        latent_uri="file:///tmp/s1_t2v.pt",
        latent_shape=[1, 16, 6, 18, 42],
    )
    assert result.status == T2VRemoteStatus.OK
    data = json.loads(result.to_json())
    assert data["status"] == "ok"
    back = T2VRemoteResult.from_dict(data)
    assert back.latent_uri.endswith("s1_t2v.pt")
    assert back.latent_shape == [1, 16, 6, 18, 42]


def test_result_ok_requires_uri_and_5d_shape():
    with pytest.raises(ValueError, match="latent_uri"):
        T2VRemoteResult(
            job_id="j", op_id="o", status=T2VRemoteStatus.OK, latent_shape=[1, 16, 6, 8, 8]
        )
    with pytest.raises(ValueError, match="5D"):
        T2VRemoteResult.ok(
            job_id="j", op_id="o", latent_uri="file:///x.pt", latent_shape=[1, 16, 8, 8]
        )


def test_result_fail_factory():
    result = T2VRemoteResult.fail(job_id="job-1", op_id="s1_t2v", error="OOM")
    assert result.status == T2VRemoteStatus.ERROR
    assert result.latent_uri is None
    assert "OOM" in result.error


def test_redis_key_helpers():
    assert REDIS_KEY_T2V_OPS == "renderflow:ops:t2v"
    assert t2v_result_key("s1_t2v") == "renderflow:ops:t2v:result:s1_t2v"


def test_expected_latent_shape_wan_defaults():
    # 21 frames, 336x144 → T=(20//4)+1=6, H=18, W=42
    assert expected_latent_shape(336, 144, 21) == [1, 16, 6, 18, 42]
    assert expected_latent_shape(512, 288, 17) == [1, 16, 5, 36, 64]


def test_enqueue_and_wait_with_fake_redis():
    """In-process fake Redis: enqueue → publish → wait (no network)."""

    class FakeRedis:
        def __init__(self) -> None:
            self.lists: dict[str, list[str]] = {}
            self.kv: dict[str, str] = {}

        def rpush(self, key: str, value: str) -> None:
            self.lists.setdefault(key, []).append(value)

        def set(self, key: str, value: str, ex: int | None = None) -> None:
            self.kv[key] = value

        def get(self, key: str) -> str | None:
            return self.kv.get(key)

    from renderflow_queue import enqueue_t2v_request, publish_t2v_result, wait_t2v_result

    r = FakeRedis()
    req = _valid_request()
    enqueue_t2v_request(r, req)
    assert len(r.lists[REDIS_KEY_T2V_OPS]) == 1

    # Simulate stub: parse queue item and publish ok.
    queued = T2VRemoteRequest.from_json(r.lists[REDIS_KEY_T2V_OPS][0])
    shape = expected_latent_shape(queued.width, queued.height, queued.num_frames)
    publish_t2v_result(
        r,
        T2VRemoteResult.ok(
            job_id=queued.job_id,
            op_id=queued.op_id,
            latent_uri="file:///tmp/fake.pt",
            latent_shape=shape,
        ),
    )

    result = wait_t2v_result(r, queued.op_id, timeout_sec=1.0, poll_interval_sec=0.01)
    assert result.status == T2VRemoteStatus.OK
    assert result.latent_shape == shape
