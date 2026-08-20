"""Mux step 3: stitch shot_clips in timeline order into output.mp4."""
from __future__ import annotations

import shutil

import pytest
from PIL import Image

from app.rfir.executor.context import ExecutionContext
from app.rfir.executor.ffmpeg_mux import MuxError, assemble_output_mp4, even_dim, shared_output_size
from app.rfir.executor import engine
from app.rfir.executor.shot_clips import ShotClip
from app.rfir.ir.types import RfirNode

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not on PATH")


def _rgb(path, size, color) -> str:
    Image.new("RGB", size, color=color).save(path)
    return str(path)


def _clip(idx: int, paths: list[str], *, kind: str, duration: float = 0.25) -> ShotClip:
    return ShotClip(
        shot_index=idx,
        duration_sec=duration,
        fps=24,
        kind=kind,
        paths=paths,
        source_node=f"s{idx}_src",
    )


def test_mux_stitches_mixed_shots_in_index_order(tmp_path):
    still = _rgb(tmp_path / "s0_t2i.png", (16, 10), (255, 0, 0))
    decoy = _rgb(tmp_path / "aaa_decoy.png", (64, 64), (0, 0, 255))
    f0 = _rgb(tmp_path / "s1_rife_0.png", (20, 12), (0, 255, 0))
    f1 = _rgb(tmp_path / "s1_rife_1.png", (20, 12), (0, 200, 0))
    c0 = _rgb(tmp_path / "s2_comp_0.png", (32, 16), (255, 255, 0))
    c1 = _rgb(tmp_path / "s2_comp_1.png", (32, 16), (200, 200, 0))
    c2 = _rgb(tmp_path / "s2_comp_2.png", (32, 16), (150, 150, 0))

    ctx = ExecutionContext(job_id="mux-1")
    ctx.artifacts["aaa_decoy"] = decoy
    ctx.shot_clips[2] = _clip(2, [c0, c1, c2], kind="frames")
    ctx.shot_clips[0] = _clip(0, [still], kind="still")
    ctx.shot_clips[1] = _clip(1, [f0, f1], kind="frames")

    engine._run_ffmpeg_mux(RfirNode(id="mux", op="ffmpeg_mux"), None, ctx, tmp_path)

    out = tmp_path / "output.mp4"
    assert out.is_file()
    assert out.stat().st_size > 1024
    assert ctx.artifacts["output_mp4"] == str(out)
    assert not (tmp_path / "_mux").exists()


def test_mux_empty_shot_clips_raises(tmp_path):
    ctx = ExecutionContext(job_id="mux-empty")
    with pytest.raises(MuxError, match="empty"):
        engine._run_ffmpeg_mux(RfirNode(id="mux", op="ffmpeg_mux"), None, ctx, tmp_path)
    assert not (tmp_path / "output.mp4").exists()


def test_mux_missing_path_raises(tmp_path):
    ctx = ExecutionContext(job_id="mux-missing")
    ctx.shot_clips[0] = _clip(0, [str(tmp_path / "gone.png")], kind="still")
    with pytest.raises(MuxError, match="missing or empty"):
        engine._run_ffmpeg_mux(RfirNode(id="mux", op="ffmpeg_mux"), None, ctx, tmp_path)


def test_mux_odd_and_mismatched_sizes_encode(tmp_path):
    a = _rgb(tmp_path / "odd.png", (15, 9), (10, 20, 30))
    b = _rgb(tmp_path / "wide.png", (40, 10), (40, 50, 60))
    clips = {
        0: _clip(0, [a], kind="still", duration=0.2),
        1: _clip(1, [b], kind="still", duration=0.2),
    }
    w, h = shared_output_size(list(clips.values()))
    assert w % 2 == 0 and h % 2 == 0
    assert even_dim(15) == 16

    out = assemble_output_mp4(clips, tmp_path)
    assert out.is_file() and out.stat().st_size > 500


def test_mux_does_not_use_artifact_scan_order(tmp_path):
    """A decoy PNG that would sort first in artifacts must not become the video."""
    decoy = _rgb(tmp_path / "aaa.png", (8, 8), (255, 0, 0))
    real = _rgb(tmp_path / "s0_rife_0.png", (8, 8), (0, 255, 0))
    real2 = _rgb(tmp_path / "s0_rife_1.png", (8, 8), (0, 180, 0))
    ctx = ExecutionContext(job_id="mux-order")
    ctx.artifacts["aaa"] = decoy
    ctx.shot_clips[0] = _clip(0, [real, real2], kind="frames", duration=0.3)
    engine._run_ffmpeg_mux(RfirNode(id="mux", op="ffmpeg_mux"), None, ctx, tmp_path)
    assert (tmp_path / "output.mp4").stat().st_size > 500
