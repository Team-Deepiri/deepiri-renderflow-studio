"""Tests for the rife_interpolate op (§2.5).

Cover the contract and the fail-safe behavior without needing torch or the
vendored weights: the real-model path is exercised via a stub model.
"""
from __future__ import annotations

import pytest
from PIL import Image

from app.rfir.ops import rife_interpolate


def _img(color: tuple[int, int, int], size=(64, 48)) -> Image.Image:
    return Image.new("RGB", size, color)


# ── blend fallback ────────────────────────────────────────────────────────────

def test_blend_fallback_count_and_endpoints():
    start, end = _img((0, 0, 0)), _img((255, 255, 255))
    frames = rife_interpolate._blend_fallback(start, end, 4)
    assert len(frames) == 5                     # start + 3 intermediates + end
    assert frames[0] is start and frames[-1] is end
    # monotonic brightness across the cross-fade
    lums = [f.convert("L").getpixel((0, 0)) for f in frames]
    assert lums == sorted(lums)


def test_blend_fallback_resizes_mismatched_end():
    start, end = _img((0, 0, 0), (64, 48)), _img((255, 255, 255), (32, 24))
    frames = rife_interpolate._blend_fallback(start, end, 2)
    assert all(f.size == (64, 48) for f in frames)


# ── run(): model unavailable → blend ──────────────────────────────────────────

def test_run_falls_back_when_model_unavailable(monkeypatch):
    def _raise(_mid):
        raise FileNotFoundError("no weights")

    monkeypatch.setattr(rife_interpolate, "load_model", _raise)
    frames = rife_interpolate.run(_img((10, 10, 10)), _img((200, 200, 200)), factor=4)
    assert len(frames) == 5
    assert frames[0].size == (64, 48)


def test_run_falls_back_when_inference_raises(monkeypatch):
    class _Boom:
        def interpolate(self, a, b, factor):
            raise RuntimeError("mps kernel exploded")

    monkeypatch.setattr(rife_interpolate, "load_model", lambda _mid: _Boom())
    frames = rife_interpolate.run(_img((0, 0, 0)), _img((255, 255, 255)), factor=3)
    assert len(frames) == 4                      # still well-formed via blend


# ── run(): real model path (stubbed) ──────────────────────────────────────────

def test_run_uses_model_and_wraps_endpoints(monkeypatch):
    start, end = _img((0, 0, 0)), _img((255, 255, 255))

    class _Stub:
        def interpolate(self, a, b, factor):
            assert a is start and b is end and factor == 4
            return [_img((i, i, i)) for i in (60, 120, 180)]  # factor-1 middles

    monkeypatch.setattr(rife_interpolate, "load_model", lambda _mid: _Stub())
    frames = rife_interpolate.run(start, end, factor=4)
    assert len(frames) == 5
    assert frames[0] is start and frames[-1] is end          # endpoints preserved


def test_run_clamps_factor_to_minimum_two(monkeypatch):
    monkeypatch.setattr(
        rife_interpolate, "load_model",
        lambda _mid: type("S", (), {"interpolate": lambda self, a, b, f: []})(),
    )
    frames = rife_interpolate.run(_img((0, 0, 0)), _img((1, 1, 1)), factor=1)
    assert len(frames) == 2                       # factor floored to 2 → [start, end]


# ── wrapper fails safe when arch not vendored ─────────────────────────────────

def test_rife_model_load_raises_without_weights(tmp_path):
    """With the arch vendored but no flownet.pkl, load fails clearly so the op
    falls back to blend rather than the pipeline crashing."""
    pytest.importorskip("torch")
    from app.rfir.models.rife import RIFEModel

    with pytest.raises((FileNotFoundError, RuntimeError)):
        RIFEModel.load(str(tmp_path), "cpu", "float32")  # empty dir → no weights
