"""shot_clips map (mux step 2): last writer wins per shot timeline index."""
from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from app.rfir.arena import TensorArena
from app.rfir.executor import engine
from app.rfir.executor.context import ExecutionContext
from app.rfir.executor.shot_clips import ShotClip, register_shot_clip, shot_index_for_node
from app.rfir.ir.types import RfirNode


def _rgb(size: tuple[int, int], color: tuple[int, int, int]) -> Image.Image:
    return Image.new("RGB", size, color=color)


def test_register_rejects_missing_paths(tmp_path):
    ctx = ExecutionContext(job_id="job-1")
    node = RfirNode(id="s0_t2i", op="t2i_keyframe", attrs={"shot_index": 0, "duration_sec": 5.0})
    register_shot_clip(ctx, 0, [str(tmp_path / "missing.png")], node)
    assert 0 not in ctx.shot_clips


def test_t2i_registers_still_for_shot(tmp_path, monkeypatch):
    monkeypatch.setattr(engine.t2i_keyframe, "run", lambda *a, **k: _rgb((4, 4), (1, 2, 3)))
    node = RfirNode(
        id="s0_t2i", op="t2i_keyframe",
        outputs={"image": "s0_keyframe"},
        attrs={"prompt": "test", "shot_index": 0, "duration_sec": 4.0},
    )
    ctx = ExecutionContext(job_id="job-1")
    arena = TensorArena()
    engine._run_t2i_keyframe(node, arena, ctx, tmp_path)

    assert 0 in ctx.shot_clips
    clip = ctx.shot_clips[0]
    assert clip.kind == "still"
    assert len(clip.paths) == 1
    assert clip.source_node == "s0_t2i"
    assert clip.duration_sec == 4.0


def test_batch_t2i_registers_multiple_shots(tmp_path, monkeypatch):
    monkeypatch.setattr(engine.t2i_keyframe, "run", lambda *a, **k: _rgb((4, 4), (9, 9, 9)))
    node = RfirNode(
        id="t2i_batch_0", op="t2i_keyframe",
        outputs={"image_0": "s0_keyframe", "image_1": "s1_keyframe"},
        attrs={
            "batch": True,
            "prompts": ["a", "b"],
            "batch_shot_indices": [0, 1],
            "shot_index": 99,
        },
    )
    ctx = ExecutionContext(job_id="job-1")
    arena = TensorArena()
    engine._run_t2i_keyframe(node, arena, ctx, tmp_path)

    assert set(ctx.shot_clips) == {0, 1}
    assert ctx.shot_clips[0].paths[0].endswith("t2i_batch_0_0.png")
    assert ctx.shot_clips[1].paths[0].endswith("t2i_batch_0_1.png")
    assert shot_index_for_node(node, batch_index=0) == 0
    assert shot_index_for_node(node, batch_index=1) == 1


def test_rife_overwrites_t2i_still(tmp_path, monkeypatch):
    monkeypatch.setattr(
        engine.rife_interpolate,
        "run",
        lambda start, end, **k: [start, end],
    )
    t2i = RfirNode(
        id="s0_t2i", op="t2i_keyframe",
        outputs={"image": "s0_keyframe"},
        attrs={"shot_index": 0, "duration_sec": 5.0},
    )
    rife = RfirNode(
        id="s0_rife", op="rife_interpolate",
        inputs={"frame_start": "s0_kf_start", "frame_end": "s0_kf_end"},
        outputs={"frames": "s0_interp"},
        attrs={"shot_index": 0, "duration_sec": 5.0},
    )
    ctx = ExecutionContext(job_id="job-1")
    arena = TensorArena()
    monkeypatch.setattr(engine.t2i_keyframe, "run", lambda *a, **k: _rgb((8, 8), (1, 1, 1)))
    engine._run_t2i_keyframe(t2i, arena, ctx, tmp_path)
    assert ctx.shot_clips[0].kind == "still"

    arena.put("s0_kf_start", _rgb((8, 8), (2, 2, 2)))
    arena.put("s0_kf_end", _rgb((8, 8), (3, 3, 3)))
    engine._run_rife_interpolate(rife, arena, ctx, tmp_path)

    assert ctx.shot_clips[0].kind == "frames"
    assert len(ctx.shot_clips[0].paths) == 2
    assert ctx.shot_clips[0].source_node == "s0_rife"


def test_composite_overwrites_prior_vae_clip(tmp_path):
    plate = (32, 16)
    comp_node = RfirNode(
        id="s0_comp", op="vulkan_composite",
        inputs={"foreground": "fg", "background": "bg", "mask": "mask"},
        outputs={"image": "s0_composite"},
        attrs={"shot_index": 0, "duration_sec": 6.0},
    )
    ctx = ExecutionContext(job_id="job-1")
    vae_paths = [str(tmp_path / "s0_vae_dec_0.png"), str(tmp_path / "s0_vae_dec_1.png")]
    for i, p in enumerate(vae_paths):
        _rgb((8, 8), (i, 0, 0)).save(p)
    ctx.shot_clips[0] = ShotClip(
        shot_index=0, duration_sec=6.0, kind="frames", paths=vae_paths, source_node="s0_vae_dec",
    )

    arena = TensorArena()
    decoded = [_rgb((8, 8), (10, 0, 0)), _rgb((8, 8), (20, 0, 0))]
    arena.put("fg", decoded)
    arena.put("bg", _rgb(plate, (0, 0, 0)))
    arena.put("mask", np.full((16, 32), 255, dtype=np.uint8))
    engine._run_vulkan_composite(comp_node, arena, ctx, tmp_path)

    assert ctx.shot_clips[0].source_node == "s0_comp"
    assert len(ctx.shot_clips[0].paths) == 2
    assert all("s0_comp_" in p for p in ctx.shot_clips[0].paths)


def test_depth_and_segment_do_not_register(tmp_path, monkeypatch):
    monkeypatch.setattr(engine.depth_estimate, "run", lambda img, **k: np.zeros((4, 4), dtype=np.float32))
    monkeypatch.setattr(engine.segment_subject, "run", lambda img: np.zeros((4, 4), dtype=np.uint8))

    depth = RfirNode(
        id="s0_depth", op="depth_estimate",
        inputs={"image": "img"}, outputs={"depth": "d"},
        attrs={"shot_index": 0},
    )
    segment = RfirNode(
        id="s0_segment", op="segment_subject",
        inputs={"image": "img"}, outputs={"mask": "m"},
        attrs={"shot_index": 0},
    )
    ctx = ExecutionContext(job_id="job-1")
    arena = TensorArena()
    arena.put("img", _rgb((4, 4), (1, 2, 3)))

    engine._run_depth_estimate(depth, arena, ctx, tmp_path)
    engine._run_segment_subject(segment, arena, ctx, tmp_path)

    assert ctx.shot_clips == {}


def test_upscale_stub_does_not_overwrite_rife_clip(tmp_path, monkeypatch):
    monkeypatch.setattr(engine.rife_interpolate, "run", lambda s, e, **k: [s, e])
    rife = RfirNode(
        id="s0_rife", op="rife_interpolate",
        inputs={"frame_start": "a", "frame_end": "b"},
        outputs={"frames": "interp"},
        attrs={"shot_index": 0, "duration_sec": 5.0},
    )
    upscale = RfirNode(
        id="s0_upscale", op="vulkan_upscale",
        inputs={"image": "interp"}, outputs={"image_out": "out"},
        attrs={"shot_index": 0},
    )
    ctx = ExecutionContext(job_id="job-1")
    arena = TensorArena()
    arena.put("a", _rgb((8, 8), (1, 0, 0)))
    arena.put("b", _rgb((8, 8), (0, 1, 0)))
    engine._run_rife_interpolate(rife, arena, ctx, tmp_path)
    before = ctx.shot_clips[0]

    arena.put("interp", [arena.get("a"), arena.get("b")])
    engine._run_vulkan_upscale_stub(upscale, arena, ctx, tmp_path)

    assert ctx.shot_clips[0] is before
    assert ctx.shot_clips[0].source_node == "s0_rife"


def test_failed_composite_raises(tmp_path, monkeypatch):
    comp_node = RfirNode(
        id="s0_comp", op="vulkan_composite",
        inputs={"foreground": "fg", "background": "bg", "mask": "mask"},
        outputs={"image": "s0_composite"},
        attrs={"shot_index": 0, "duration_sec": 5.0},
    )
    ctx = ExecutionContext(job_id="job-1")
    prior = str(tmp_path / "s0_t2i.png")
    _rgb((8, 8), (5, 5, 5)).save(prior)
    ctx.shot_clips[0] = ShotClip(
        shot_index=0, duration_sec=5.0, kind="still", paths=[prior], source_node="s0_bg_t2i",
    )

    arena = TensorArena()
    arena.put("fg", [_rgb((8, 8), (5, 5, 5))])
    arena.put("bg", _rgb((32, 16), (0, 0, 0)))
    arena.put("mask", np.full((16, 32), 255, dtype=np.uint8))

    def _fail_save(self, *args, **kwargs):
        raise OSError("fail")

    monkeypatch.setattr(Image.Image, "save", _fail_save)
    with pytest.raises(RuntimeError, match="could not be composited"):
        engine._run_vulkan_composite(comp_node, arena, ctx, tmp_path)

    assert 0 not in ctx.shot_clips or ctx.shot_clips[0].source_node != "s0_comp"


def test_tier_c_vae_decode_does_not_register(tmp_path, monkeypatch):
    torch = pytest.importorskip("torch")
    frames = [_rgb((8, 8), (1, 0, 0)), _rgb((8, 8), (0, 1, 0))]
    monkeypatch.setattr(engine.vae, "decode", lambda *a, **k: frames)
    monkeypatch.setattr(engine, "unload_all", lambda: None)
    monkeypatch.setattr(engine, "reclaim_accelerator_memory", lambda: None)

    node = RfirNode(
        id="s0_vae_dec", op="vae_decode",
        inputs={"latent": "lat"}, outputs={"image": "s0_fg"},
        attrs={"shot_index": 0, "duration_sec": 5.0, "register_clip": False},
    )
    ctx = ExecutionContext(job_id="job-1")
    arena = TensorArena()
    arena.put("lat", torch.zeros(1))

    engine._run_vae_decode(node, arena, ctx, tmp_path)

    assert (tmp_path / "s0_vae_dec_0.png").is_file()
    assert (tmp_path / "s0_vae_dec_1.png").is_file()
    assert ctx.shot_clips == {}


def test_tier_d_vae_decode_registers(tmp_path, monkeypatch):
    torch = pytest.importorskip("torch")
    frames = [_rgb((8, 8), (1, 0, 0)), _rgb((8, 8), (0, 1, 0))]
    monkeypatch.setattr(engine.vae, "decode", lambda *a, **k: frames)
    monkeypatch.setattr(engine, "unload_all", lambda: None)
    monkeypatch.setattr(engine, "reclaim_accelerator_memory", lambda: None)

    node = RfirNode(
        id="s0_vae_dec", op="vae_decode",
        inputs={"latent": "lat"}, outputs={"image": "s0_frames"},
        attrs={"shot_index": 0, "duration_sec": 3.0},
    )
    ctx = ExecutionContext(job_id="job-1")
    arena = TensorArena()
    arena.put("lat", torch.zeros(1))

    engine._run_vae_decode(node, arena, ctx, tmp_path)

    assert ctx.shot_clips[0].source_node == "s0_vae_dec"
    assert len(ctx.shot_clips[0].paths) == 2

