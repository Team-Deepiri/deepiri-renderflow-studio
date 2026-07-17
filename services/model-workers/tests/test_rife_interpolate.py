"""Tests for the rife_interpolate op (§2.5).

Cover the contract and the fail-safe behavior without needing torch or the
vendored weights: the real-model path is exercised via a stub model.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from app.rfir.ops import rife_interpolate

# In-repo LFS weights; the real-model test below skips if they aren't present.
_RIFE_WEIGHTS = Path(__file__).resolve().parents[1] / "models" / "rife-4.6" / "flownet.pkl"


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


# ── real vendored net + LFS weights (skipped when weights aren't pulled) ───────

@pytest.mark.skipif(not _RIFE_WEIGHTS.is_file(),
                    reason="RIFE weights not present (run `git lfs pull`)")
def test_rife_real_model_loads_and_interpolates():
    """When the vendored arch + LFS weights are present, the real IFNet loads
    and produces `factor - 1` intermediates at the input size."""
    pytest.importorskip("torch")
    from app.rfir.models.rife import RIFEModel

    model = RIFEModel.load(str(_RIFE_WEIGHTS.parent), "cpu", "float32")
    mids = model.interpolate(_img((0, 0, 0)), _img((255, 255, 255)), factor=4)
    assert len(mids) == 3                              # factor-1 intermediates
    assert all(f.size == _img((0, 0, 0)).size for f in mids)


# ── loader: RIFE weight-path resolution & fail-safe  ─────────────────────

from app.rfir.models import loader as rife_loader          # noqa: E402
from app.rfir.models.registry import get_manifest          # noqa: E402


def _rife_manifest():
    m = get_manifest("rife-4.6")
    assert m is not None                                   # registry sanity
    return m


def _stub_rife_load(monkeypatch, captured: dict):
    """Replace RIFEModel.load with a recorder; returns nothing, mutates captured."""
    import app.rfir.models.rife as rife_pkg

    class _FakeRIFE:
        @staticmethod
        def load(path, device, dtype):
            captured.update(path=path, device=device, dtype=dtype)
            return "MODEL"

    # _load_rife does `from app.rfir.models.rife import RIFEModel` at call time,
    # so patch the attribute on the package module.
    monkeypatch.setattr(rife_pkg, "RIFEModel", _FakeRIFE)


def test_default_models_root_finds_package_marker():
    """Walk-up resolves to <package-root>/models, next to pyproject.toml."""
    root = rife_loader._default_models_root()
    assert root is not None
    assert root.name == "models"
    assert (root.parent / "pyproject.toml").is_file()


def test_load_rife_raises_when_models_dir_unresolvable(monkeypatch):
    """No $RENDERFLOW_MODELS_DIR and no package marker → clear RuntimeError
    (the op catches it and blends) instead of a silently wrong path."""
    monkeypatch.delenv("RENDERFLOW_MODELS_DIR", raising=False)
    monkeypatch.setattr(rife_loader, "_MODELS_ROOT", None)
    with pytest.raises(RuntimeError, match="Cannot locate the models directory"):
        rife_loader._load_rife(_rife_manifest(), "cpu", None)


def test_load_rife_raises_when_weights_missing(monkeypatch, tmp_path):
    """Resolvable dir but no flownet.pkl → FileNotFoundError that points the
    operator at `git lfs pull`."""
    monkeypatch.setenv("RENDERFLOW_MODELS_DIR", str(tmp_path))
    with pytest.raises(FileNotFoundError, match="git lfs pull"):
        rife_loader._load_rife(_rife_manifest(), "cpu", None)


@pytest.mark.parametrize("source, device, expected_dtype", [
    ("env", "cuda", "float16"),   # $RENDERFLOW_MODELS_DIR wins; cuda → fp16
    ("root", "cpu", "float32"),   # no env var → resolve under _MODELS_ROOT; → fp32
])

def test_load_rife_resolves_weights_dir_and_dtype(
    monkeypatch, tmp_path, source, device, expected_dtype
):
    """Weights resolve to <models-dir>/<id>/, dtype is device-driven, and the
    env var takes precedence over _MODELS_ROOT."""
    weights_dir = tmp_path / "rife-4.6"
    weights_dir.mkdir()
    (weights_dir / "flownet.pkl").write_bytes(b"stub")
    if source == "env":
        monkeypatch.setenv("RENDERFLOW_MODELS_DIR", str(tmp_path))
        monkeypatch.setattr(rife_loader, "_MODELS_ROOT", Path("/should/not/be/used"))
    else:
        monkeypatch.delenv("RENDERFLOW_MODELS_DIR", raising=False)
        monkeypatch.setattr(rife_loader, "_MODELS_ROOT", tmp_path)

    captured: dict = {}
    _stub_rife_load(monkeypatch, captured)

    out = rife_loader._load_rife(_rife_manifest(), device, None)
    assert out == "MODEL"
    assert captured["path"] == str(weights_dir)
    assert captured["device"] == device
    assert captured["dtype"] == expected_dtype
