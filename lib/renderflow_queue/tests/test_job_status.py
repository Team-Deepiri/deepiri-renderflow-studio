"""Tests for the RFIR job status write-back contract (in-memory fake Redis)."""
import json

from renderflow_queue import JobStatusReporter, RfirJobState, RfirJobStatus


class FakeRedis:
    """Minimal in-memory stand-in for the subset of redis-py used here."""

    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    def set(self, key: str, value: str, ex: int | None = None) -> None:
        self._store[key] = value

    def get(self, key: str) -> str | None:
        return self._store.get(key)

    def delete(self, key: str) -> None:
        self._store.pop(key, None)


def test_set_and_get_status_roundtrip():
    r = FakeRedis()
    reporter = JobStatusReporter(r)

    status = RfirJobStatus(job_id="job-1", state=RfirJobState.RUNNING, stage="t2i_keyframe")
    reporter.set_status(status)

    fetched = reporter.get_status("job-1")
    assert fetched is not None
    assert fetched.job_id == "job-1"
    assert fetched.state == RfirJobState.RUNNING
    assert fetched.stage == "t2i_keyframe"


def test_get_status_missing_returns_none():
    reporter = JobStatusReporter(FakeRedis())
    assert reporter.get_status("nonexistent") is None


def test_clear_status_removes_key():
    r = FakeRedis()
    reporter = JobStatusReporter(r)
    reporter.set_status(RfirJobStatus(job_id="job-2", state=RfirJobState.PREPARING))
    assert reporter.get_status("job-2") is not None

    reporter.clear_status("job-2")
    assert reporter.get_status("job-2") is None


def test_terminal_states():
    review = RfirJobStatus(job_id="j", state=RfirJobState.REVIEW)
    failed = RfirJobStatus(job_id="j", state=RfirJobState.FAILED)
    running = RfirJobStatus(job_id="j", state=RfirJobState.RUNNING)

    assert review.is_terminal is True
    assert failed.is_terminal is True
    assert running.is_terminal is False


def test_status_carries_artifacts_and_metrics():
    r = FakeRedis()
    reporter = JobStatusReporter(r)

    status = RfirJobStatus(
        job_id="job-3",
        state=RfirJobState.REVIEW,
        artifacts={"output_mp4": "/out/output.mp4"},
        metrics={"total_gpu_ms": 1234.5, "cost_estimate_usd": 0.01},
    )
    reporter.set_status(status)

    fetched = reporter.get_status("job-3")
    assert fetched.artifacts == {"output_mp4": "/out/output.mp4"}
    assert fetched.metrics["total_gpu_ms"] == 1234.5


def test_status_carries_error_on_failure():
    r = FakeRedis()
    reporter = JobStatusReporter(r)

    status = RfirJobStatus(job_id="job-4", state=RfirJobState.FAILED, error="model load failed")
    reporter.set_status(status)

    fetched = reporter.get_status("job-4")
    assert fetched.error == "model load failed"
    assert fetched.is_terminal is True


def test_to_dict_is_json_serializable():
    status = RfirJobStatus(job_id="j", state=RfirJobState.RUNNING, metadata={"a": 1})
    raw = json.dumps(status.to_dict())
    assert isinstance(raw, str)
