"""Is the Tier B SSIM gate viable once keyframes are seed-locked + delta'd?

Experiment 1 (seedlock_experiment.py) tested the keyframe PAIR. This tests
the GATE: generate start / verify / end seed-locked with prompt deltas, run
the interpolator, and score its midpoint against the verification keyframe —
exactly what engine._run_ssim_gate does.

Two verify-prompt strategies, because Step 7b left this a choose-one and the
review said the fallback must not ship:

  MID  planner emits a real midpoint prompt      (the "do it properly" option)
  END  verify reuses description_end              (the doc's fallback)

If END scores systematically below MID, the fallback is measuring the wrong
thing and would bias toward escalating every shot — confirming the review.

NOTE: RIFE weights are not present in this environment, so rife_interpolate
falls back to a linear blend (_blend_fallback). That is also what would run
on this machine today, so the gate scores here are the ones this environment
would actually produce.
"""
from __future__ import annotations

import json
import os
import statistics
import sys
import time
from pathlib import Path

os.environ.setdefault("RENDERFLOW_RFIR_T2I_MODEL", "sdxl-turbo-fp16")
os.environ.setdefault("RENDERFLOW_RFIR_WARMUP", "0")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.rfir.ops import rife_interpolate, t2i_keyframe  # noqa: E402
from app.rfir.executor.context import decide_escalation  # noqa: E402
from tier_b_seedlock_experiment import ssim  # noqa: E402

OUT = Path(__file__).parent / "gate_out"
OUT.mkdir(exist_ok=True)

W, H, STEPS = 512, 288, 2
FACTOR = 4  # engine default -> 5 frames -> midpoint is frames[2]

# (start, midpoint, end)
TRIPLES = [
    ("a dancer standing with arms down, studio light",
     "a dancer standing with arms half raised, studio light",
     "a dancer standing with arms raised, studio light"),
    ("a man walking on a city street, morning",
     "a man walking a little further down a city street, morning",
     "a man walking further down a city street, morning"),
    ("a cat sitting on a windowsill",
     "a cat beginning to stretch on a windowsill",
     "a cat stretching on a windowsill"),
    ("a red sports car parked on a coastal road",
     "a red sports car pulling away on a coastal road",
     "a red sports car driving along a coastal road"),
    ("a woman sitting at a cafe table reading",
     "a woman sitting at a cafe table glancing up from a book",
     "a woman sitting at a cafe table looking up"),
    ("a runner crouched at a starting line on a track",
     "a runner rising from a starting line on a track",
     "a runner pushing off from a starting line on a track"),
    ("a tree in a field with still branches",
     "a tree in a field with branches beginning to sway",
     "a tree in a field with branches bending in wind"),
    ("a chef standing over a pan in a kitchen",
     "a chef lifting a pan in a kitchen",
     "a chef tossing food in a pan in a kitchen"),
    ("a child holding a balloon in a park",
     "a child loosening grip on a balloon in a park",
     "a child releasing a balloon in a park"),
    ("a surfer paddling on a wave",
     "a surfer rising to their knees on a wave",
     "a surfer standing up on a wave"),
]


def gen(prompt, seed):
    return t2i_keyframe.run(prompt, width=W, height=H, steps=STEPS, seed=seed)


def main() -> None:
    n = int(os.environ.get("N_PAIRS", "10"))
    triples = TRIPLES[:n]

    t0 = time.monotonic()
    gen("warmup", 0)
    print(f"warmup/JIT: {time.monotonic() - t0:.0f}s")

    probe = rife_interpolate.run(gen("a cat", 7), gen("a dog", 7), factor=FACTOR)
    print(f"interpolator returns {len(probe)} frames for factor={FACTOR} "
          f"(blend fallback: RIFE weights absent)\n")

    rows = []
    for i, (p_start, p_mid, p_end) in enumerate(triples):
        seed = 2000 + i
        start, verify_mid, end = gen(p_start, seed), gen(p_mid, seed), gen(p_end, seed)

        frames = rife_interpolate.run(start, end, factor=FACTOR)
        midpoint = frames[len(frames) // 2]

        s_mid = ssim(midpoint, verify_mid)   # MID strategy
        s_end = ssim(midpoint, end)          # END fallback (verify == end image)
        rows.append({"i": i, "prompt": p_start, "MID": s_mid, "END": s_end})

        d_mid = decide_escalation(s_mid, escalations_remaining=1)
        d_end = decide_escalation(s_end, escalations_remaining=1)
        print(f"[{i:2d}] MID={s_mid:.4f} ({'ESC' if d_mid.escalate else 'ok '})  "
              f"END={s_end:.4f} ({'ESC' if d_end.escalate else 'ok '})  {p_start[:38]}")

        midpoint.save(OUT / f"{i:02d}_midpoint.png")
        verify_mid.save(OUT / f"{i:02d}_verify_mid.png")
        start.save(OUT / f"{i:02d}_start.png")
        end.save(OUT / f"{i:02d}_end.png")

    print("\n" + "=" * 70)
    for name in ("MID", "END"):
        v = sorted(r[name] for r in rows)
        esc = sum(1 for x in v if decide_escalation(x, escalations_remaining=1).escalate)
        print(f"\n{name}  mean={statistics.mean(v):.4f}  median={statistics.median(v):.4f}  "
              f"stdev={statistics.stdev(v):.4f}  min={v[0]:.4f}  max={v[-1]:.4f}")
        print(f"  sorted: {[round(x, 3) for x in v]}")
        print(f"  escalates at the current 0.85 threshold: {esc}/{len(v)}")

    mids = [r["MID"] for r in rows]
    ends = [r["END"] for r in rows]
    print("\n" + "=" * 70)
    print(f"MID - END mean difference = {statistics.mean(mids) - statistics.mean(ends):+.4f}")
    print(f"pairs where MID > END: {sum(1 for a, b in zip(mids, ends) if a > b)}/{len(mids)}")

    v = sorted(mids)
    print(f"\nthreshold calibration from observed MID distribution:")
    for q, lab in ((0.10, "p10"), (0.25, "p25"), (0.50, "p50")):
        k = max(0, int(q * len(v)) - 1)
        print(f"  {lab} = {v[k]:.3f}   (a threshold here escalates ~{int(q*100)}% of shots)")

    (OUT / "results.json").write_text(json.dumps({"rows": rows}, indent=2))
    print(f"\nimages + results.json -> {OUT}")


if __name__ == "__main__":
    main()
