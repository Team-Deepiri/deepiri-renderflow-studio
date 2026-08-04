"""Tests for Layer 3 — runtime guard (model-worker side).

Policy tests stub _nsfw_score so they don't need model weights; the scoring
path itself (label lookup, softmax, dtype handling) is covered separately
with a fake model bundle.
"""
from __future__ import annotations

import io
from types import SimpleNamespace

import pytest
import torch
from diri_agent_guardrails.core.verdict import Verdict
from PIL import Image

from app.guardrails import runtime_guard
from app.guardrails.runtime_guard import check_budget, check_keyframe


def _png_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), color=(120, 120, 120)).save(buf, format="PNG")
    return buf.getvalue()


# --- nsfw_mode policy -------------------------------------------------------


def test_off_mode_allows_without_running_the_classifier(monkeypatch):
    """"off" must short-circuit — no model load, no inference cost."""
    def _boom(*_a, **_k):
        raise AssertionError("classifier must not run when nsfw_mode='off'")

    monkeypatch.setattr(runtime_guard, "_nsfw_score", _boom)

    result = check_keyframe(_png_bytes(), "off", frame_index=0)
    assert result.passed
    assert result.verdict == Verdict.ALLOW


def test_low_score_allows(monkeypatch):
    monkeypatch.setattr(runtime_guard, "_nsfw_score", lambda _b: 0.02)
    result = check_keyframe(_png_bytes(), "block")
    assert result.passed
    assert result.score == pytest.approx(0.02)


def test_high_score_blocks(monkeypatch):
    monkeypatch.setattr(runtime_guard, "_nsfw_score", lambda _b: 0.95)
    result = check_keyframe(_png_bytes(), "block", frame_index=3)

    assert not result.passed
    assert result.verdict == Verdict.BLOCK
    assert result.details["frame_index"] == 3
    assert "0.95" in result.message


def test_restricted_uses_a_higher_bar_than_block(monkeypatch):
    """A score between the two thresholds blocks under "block" but passes
    under "restricted" — the coarse proxy for "artistic but not explicit"."""
    monkeypatch.setattr(runtime_guard, "_nsfw_score", lambda _b: 0.80)

    assert not check_keyframe(_png_bytes(), "block").passed
    assert check_keyframe(_png_bytes(), "restricted").passed


def test_unknown_mode_falls_back_to_block_threshold(monkeypatch):
    monkeypatch.setattr(runtime_guard, "_nsfw_score", lambda _b: 0.75)
    assert not check_keyframe(_png_bytes(), "not-a-real-mode").passed


# --- classifier failure handling --------------------------------------------


def _raise(*_a, **_k):
    raise RuntimeError("weights missing")


def test_classifier_failure_allows_in_dev(monkeypatch):
    monkeypatch.setenv("READINESS_MODE", "dev")
    monkeypatch.setattr(runtime_guard, "_nsfw_score", _raise)

    result = check_keyframe(_png_bytes(), "block")
    assert result.passed
    assert "weights missing" in result.details["classifier_error"]


def test_classifier_failure_fails_closed_in_prod(monkeypatch):
    monkeypatch.setenv("READINESS_MODE", "prod")
    monkeypatch.setattr(runtime_guard, "_nsfw_score", _raise)

    with pytest.raises(RuntimeError, match="weights missing"):
        check_keyframe(_png_bytes(), "block")


# --- scoring path -----------------------------------------------------------


def _fake_bundle(id2label, logits):
    class _Model:
        config = SimpleNamespace(id2label=id2label)
        dtype = torch.float32

        def __call__(self, pixel_values=None):
            return SimpleNamespace(logits=logits)

    def _processor(images=None, return_tensors=None):
        return {"pixel_values": torch.zeros(1, 3, 8, 8)}

    return {"model": _Model(), "processor": _processor, "device": "cpu"}


def test_nsfw_score_resolves_label_by_name_not_index(monkeypatch):
    """id2label order varies between checkpoints — the nsfw probability must
    be picked by label, so swapping models via the registry stays safe."""
    # "nsfw" is index 0 here (reversed vs Falconsai's usual ordering).
    logits = torch.tensor([[5.0, 0.0]])
    bundle = _fake_bundle({0: "nsfw", 1: "normal"}, logits)

    import app.rfir.models.loader as loader_mod
    monkeypatch.setattr(loader_mod, "load_model", lambda _id: bundle)

    score = runtime_guard._nsfw_score(_png_bytes())
    assert score > 0.9


def test_nsfw_score_raises_when_no_nsfw_label(monkeypatch):
    bundle = _fake_bundle({0: "cat", 1: "dog"}, torch.tensor([[1.0, 2.0]]))

    import app.rfir.models.loader as loader_mod
    monkeypatch.setattr(loader_mod, "load_model", lambda _id: bundle)

    with pytest.raises(RuntimeError, match="no 'nsfw' label"):
        runtime_guard._nsfw_score(_png_bytes())


# --- GPU budget (unchanged, still uncalled by the executor) ------------------


def test_check_budget_blocks_over_budget():
    result = check_budget(elapsed_gpu_sec=10.0, max_gpu_seconds=5.0)
    assert not result.passed
    assert result.verdict == Verdict.BLOCK


def test_check_budget_allows_within_budget():
    result = check_budget(elapsed_gpu_sec=2.0, max_gpu_seconds=5.0)
    assert result.passed
