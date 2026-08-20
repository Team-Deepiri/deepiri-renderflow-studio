"""Persisting every vulkan_composite frame (mux step 1), not just frame 0."""
from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from app.rfir.arena import TensorArena
from app.rfir.executor import engine
from app.rfir.executor.context import ExecutionContext
from app.rfir.ir.types import RfirNode


def _node() -> RfirNode:
    return RfirNode(
        id="s0_comp",
        op="vulkan_composite",
        inputs={"foreground": "fg", "background": "bg", "mask": "mask"},
        outputs={"image": "composite"},
        attrs={"shot_index": 0, "duration_sec": 5.0},
    )


def _rgb(size: tuple[int, int], color: tuple[int, int, int]) -> Image.Image:
    return Image.new("RGB", size, color=color)


def test_composite_saves_every_frame(tmp_path):
    node = _node()
    arena = TensorArena()
    ctx = ExecutionContext(job_id="job-1")
    plate = (32, 16)
    arena.put("fg", [_rgb((8, 8), (255, 0, 0)), _rgb((8, 8), (0, 255, 0)), _rgb((8, 8), (0, 0, 255))])
    arena.put("bg", _rgb(plate, (10, 10, 10)))
    mask = np.full((16, 32), 255, dtype=np.uint8)
    arena.put("mask", mask)

    engine._run_vulkan_composite(node, arena, ctx, tmp_path)

    paths = [tmp_path / f"s0_comp_{i}.png" for i in range(3)]
    assert all(p.is_file() and p.stat().st_size > 0 for p in paths)
    for i, path in enumerate(paths):
        img = Image.open(path)
        assert img.size == plate, f"frame {i} size {img.size} != plate {plate}"
        assert ctx.artifacts[f"s0_comp_{i}"] == str(path)
    assert ctx.artifacts["s0_comp"] == str(paths[0])
    assert isinstance(arena.get("composite"), list)
    assert len(arena.get("composite")) == 3
    assert 0 in ctx.shot_clips
    assert ctx.shot_clips[0].source_node == "s0_comp"
    assert ctx.shot_clips[0].paths == [str(p) for p in paths]


def test_missing_inputs_do_not_write_shot_artifacts(tmp_path):
    node = _node()
    arena = TensorArena()
    ctx = ExecutionContext(job_id="job-1")
    arena.put("fg", _rgb((8, 8), (1, 2, 3)))

    with pytest.raises(RuntimeError, match="could not be composited"):
        engine._run_vulkan_composite(node, arena, ctx, tmp_path)

    assert not list(tmp_path.glob("s0_comp*.png"))
    assert "s0_comp" not in ctx.artifacts
    assert not any(k.startswith("s0_comp_") for k in ctx.artifacts)


def test_empty_fg_list_is_not_a_shot(tmp_path):
    node = _node()
    arena = TensorArena()
    ctx = ExecutionContext(job_id="job-1")
    arena.put("fg", [])
    arena.put("bg", _rgb((32, 16), (0, 0, 0)))

    with pytest.raises(RuntimeError, match="could not be composited"):
        engine._run_vulkan_composite(node, arena, ctx, tmp_path)

    assert not list(tmp_path.glob("s0_comp*.png"))
    assert "s0_comp" not in ctx.artifacts


def test_attr_size_mismatch_does_not_save_shot(tmp_path):
    node = _node()
    node.attrs["width"] = 64
    node.attrs["height"] = 32
    arena = TensorArena()
    ctx = ExecutionContext(job_id="job-1")
    arena.put("fg", [_rgb((8, 8), (255, 0, 0))])
    arena.put("bg", _rgb((32, 16), (10, 10, 10)))

    with pytest.raises(RuntimeError, match="could not be composited"):
        engine._run_vulkan_composite(node, arena, ctx, tmp_path)

    assert not list(tmp_path.glob("s0_comp*.png"))
    assert "s0_comp" not in ctx.artifacts
    assert arena.get("composite") is arena.get("fg")


def test_persist_failure_rolls_back_partial_files(tmp_path, monkeypatch):
    node = _node()
    arena = TensorArena()
    ctx = ExecutionContext(job_id="job-1")
    arena.put("fg", [_rgb((8, 8), (255, 0, 0)), _rgb((8, 8), (0, 255, 0))])
    arena.put("bg", _rgb((32, 16), (10, 10, 10)))

    real_save = Image.Image.save
    calls = {"n": 0}

    def _fail_second(self, *args, **kwargs):
        calls["n"] += 1
        if calls["n"] >= 2:
            raise OSError("disk full")
        return real_save(self, *args, **kwargs)

    monkeypatch.setattr(Image.Image, "save", _fail_second)
    with pytest.raises(RuntimeError, match="could not be composited"):
        engine._run_vulkan_composite(node, arena, ctx, tmp_path)

    assert not list(tmp_path.glob("s0_comp*.png"))
    assert "s0_comp" not in ctx.artifacts
    assert "s0_comp_0" not in ctx.artifacts
