"""Does seed-lock + prompt delta give coherent Tier B keyframe pairs?

Tests the Step 7b premise empirically, per the code review's challenge:
"build 20 pairs, score SSIM, look at the distribution. If it's bimodal
you've learned the approach doesn't hold."

Conditions, all at the builder's exact Tier B settings (512x288, steps=2):

  A  today      same prompt, two independent random seeds   (Cause 5 baseline)
  B  seed-lock  same prompt, same seed                      (determinism control)
  C  proposal   start/end prompt delta, same seed           (under test)

C is viable only if it sits clearly above A (composition is actually shared)
and clearly below B's 1.0 (something actually changes), with a tight,
unimodal distribution. A bimodal C means the approach is a coin flip.
"""
from __future__ import annotations

import json
import os
import random
import statistics
import sys
import time
from pathlib import Path

os.environ.setdefault("RENDERFLOW_RFIR_T2I_MODEL", "sdxl-turbo-fp16")
os.environ.setdefault("RENDERFLOW_RFIR_WARMUP", "0")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.rfir.ops import t2i_keyframe  # noqa: E402

OUT = Path(__file__).parent / "seedlock_out"
OUT.mkdir(exist_ok=True)

W, H, STEPS = 512, 288, 2  # exactly what _build_tier_b emits

# Start/end pairs of the kind a planner would emit for a Tier B shot:
# moderate motion, same scene, one thing changes.
PAIRS = [
    ("a dancer standing with arms down, studio light",
     "a dancer standing with arms raised, studio light"),
    ("a man walking on a city street, morning",
     "a man walking further down a city street, morning"),
    ("a cat sitting on a windowsill",
     "a cat stretching on a windowsill"),
    ("a red sports car parked on a coastal road",
     "a red sports car driving along a coastal road"),
    ("a woman sitting at a cafe table reading",
     "a woman sitting at a cafe table looking up"),
    ("a runner crouched at a starting line on a track",
     "a runner pushing off from a starting line on a track"),
    ("a tree in a field with still branches",
     "a tree in a field with branches bending in wind"),
    ("a chef standing over a pan in a kitchen",
     "a chef tossing food in a pan in a kitchen"),
    ("a child holding a balloon in a park",
     "a child releasing a balloon in a park"),
    ("a surfer paddling on a wave",
     "a surfer standing up on a wave"),
]


def _ssim_arrays(x, y, *, win: int = 7, data_range: float = 255.0) -> float:
    """SSIM matching skimage.metrics.structural_similarity defaults for 2D
    input: uniform win_size=7 window, K1=0.01, K2=0.03, unbiased covariance,
    mean over the valid (cropped) region.

    Reimplemented in numpy because scikit-image is declared in pyproject.toml
    but is not installed in this venv — the same reason engine.compute_ssim
    raises ImportError at runtime today.
    """
    import numpy as np
    from numpy.lib.stride_tricks import sliding_window_view

    wx = sliding_window_view(x, (win, win))
    wy = sliding_window_view(y, (win, win))
    ax = (-1, -2)

    ux, uy = wx.mean(ax), wy.mean(ax)
    vx, vy = wx.var(ax, ddof=1), wy.var(ax, ddof=1)
    n = win * win
    vxy = ((wx * wy).mean(ax) - ux * uy) * (n / (n - 1))

    c1 = (0.01 * data_range) ** 2
    c2 = (0.03 * data_range) ** 2
    s = ((2 * ux * uy + c1) * (2 * vxy + c2)) / ((ux**2 + uy**2 + c1) * (vx + vy + c2))
    return float(s.mean())


def ssim(a, b) -> float:
    """Mirror engine.compute_ssim: greyscale, resize-to-match, clamp to [0,1]."""
    import numpy as np

    arr_a = np.asarray(a.convert("L"), dtype="float64")
    b2 = b.resize(a.size) if b.size != a.size else b
    arr_b = np.asarray(b2.convert("L"), dtype="float64")
    return float(max(0.0, min(1.0, _ssim_arrays(arr_a, arr_b))))


def gen(prompt: str, seed):
    return t2i_keyframe.run(prompt, width=W, height=H, steps=STEPS, seed=seed)


def main() -> None:
    n = int(os.environ.get("N_PAIRS", "10"))
    pairs = PAIRS[:n]

    print(f"model={os.environ['RENDERFLOW_RFIR_T2I_MODEL']} {W}x{H} steps={STEPS} pairs={len(pairs)}")
    t0 = time.monotonic()
    gen("warmup", 0)
    print(f"warmup/JIT: {time.monotonic() - t0:.0f}s\n")

    # --- B: determinism control -------------------------------------------
    p0 = pairs[0][0]
    b1, b2 = gen(p0, 1234), gen(p0, 1234)
    b_score = ssim(b1, b2)
    print(f"[B] seed-lock, same prompt, generated twice: SSIM={b_score:.4f}")
    if b_score < 0.999:
        print("    WARNING: generation is NOT deterministic under a fixed seed.")
        print("    Seed-locking cannot deliver reproducibility on this backend.")
    print()

    rng = random.Random(0)
    rows = []
    for i, (p_start, p_end) in enumerate(pairs):
        seed = 1000 + i

        start = gen(p_start, seed)
        end_c = gen(p_end, seed)          # C: seed-locked + delta
        a1 = gen(p_start, rng.randrange(2**31))  # A: today
        a2 = gen(p_start, rng.randrange(2**31))

        c = ssim(start, end_c)
        a = ssim(a1, a2)
        rows.append({"i": i, "prompt": p_start, "C_seedlock_delta": c, "A_today": a})
        print(f"[{i:2d}] C(seed-lock+delta)={c:.4f}   A(today)={a:.4f}   {p_start[:44]}")

        start.save(OUT / f"{i:02d}_C_start.png")
        end_c.save(OUT / f"{i:02d}_C_end.png")
        a1.save(OUT / f"{i:02d}_A_1.png")
        a2.save(OUT / f"{i:02d}_A_2.png")

    def describe(name, vals):
        vals = sorted(vals)
        print(f"\n{name}  n={len(vals)}")
        print(f"  mean={statistics.mean(vals):.4f}  median={statistics.median(vals):.4f}  "
              f"stdev={statistics.stdev(vals):.4f}" if len(vals) > 1 else "")
        print(f"  min={vals[0]:.4f}  max={vals[-1]:.4f}")
        print(f"  sorted: {[round(v, 3) for v in vals]}")
        return vals

    print("\n" + "=" * 70)
    c_vals = describe("C  seed-lock + prompt delta", [r["C_seedlock_delta"] for r in rows])
    a_vals = describe("A  today (same prompt, random seeds)", [r["A_today"] for r in rows])

    # Separation: does seed-locking actually buy shared composition?
    print("\n" + "=" * 70)
    sep = statistics.mean(c_vals) - statistics.mean(a_vals)
    print(f"separation (mean C - mean A) = {sep:+.4f}")

    # Bimodality probe: biggest gap in the sorted C values, and how many
    # land in a 'coherent' band vs down at baseline.
    gaps = [(c_vals[i + 1] - c_vals[i], i) for i in range(len(c_vals) - 1)]
    gap, idx = max(gaps)
    print(f"largest gap in sorted C = {gap:.4f} between {c_vals[idx]:.3f} and {c_vals[idx+1]:.3f}")
    a_max = max(a_vals)
    n_at_baseline = sum(1 for v in c_vals if v <= a_max)
    print(f"C pairs scoring at-or-below the WORST-case A pair ({a_max:.3f}): "
          f"{n_at_baseline}/{len(c_vals)}")

    (OUT / "results.json").write_text(json.dumps(
        {"determinism_ssim": b_score, "rows": rows,
         "C": c_vals, "A": a_vals, "separation": sep}, indent=2))
    print(f"\nimages + results.json -> {OUT}")


if __name__ == "__main__":
    main()
