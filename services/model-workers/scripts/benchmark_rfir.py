#!/usr/bin/env python
"""RFIR inference engine benchmark.

Runs a Tier A pipeline (t2i_keyframe + depth_estimate + ffmpeg_mux) with the
locally-cached SDXL-Turbo and Depth-Anything-V2-Small weights and reports:
  - Wall-clock time per op
  - Process RAM before / after model load
  - Peak VRAM per op (CUDA) or current allocated (MPS)
  - Total pipeline latency
  - Prometheus metrics snapshot

Usage (from repo root):
  cd services/model-workers
  RENDERFLOW_RFIR_T2I_MODEL=sdxl-turbo-fp16 poetry run python scripts/benchmark_rfir.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time

# Locate the app package.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psutil

os.environ.setdefault("RENDERFLOW_RFIR_T2I_MODEL", "sdxl-turbo-fp16")


def _mb(b: float) -> str:
    return f"{b:,.0f} MB"


def _ms(ms: float) -> str:
    if ms >= 1000:
        return f"{ms/1000:.2f} s"
    return f"{ms:.0f} ms"


def main() -> None:
    proc = psutil.Process()

    print("=" * 62)
    print("  RFIR Inference Engine Benchmark")
    print("=" * 62)

    # ---- 1. Baseline process memory before importing torch / models ----
    baseline_ram = proc.memory_info().rss / 1048576
    print(f"\nBaseline process RAM (pre-import): {_mb(baseline_ram)}")

    from app.rfir.models.loader import detect_device
    from app.rfir.profiler import sample as mem_sample, _ram_mb

    device = detect_device()
    print(f"Device: {device.upper()}")

    # ---- 2. Import torch and measure RAM cost ----
    import torch
    after_torch_import = proc.memory_info().rss / 1048576
    print(f"After torch import:                {_mb(after_torch_import)}  (+{_mb(after_torch_import - baseline_ram)})")

    # ---- 3. Compile a Tier A graph ----
    print("\n--- Compiling Tier A graph ---")
    from app.rfir.compiler.builder import build
    from app.rfir.planner import plan
    from app.rfir.ir.types import InferenceBudget, Tier

    t_compile = time.monotonic()
    shot_list = plan("a cartoon dog climbing the great pyramid of giza", guardrail=lambda _: True)
    budget = InferenceBudget(max_gpu_seconds=60, max_tier=Tier.A)
    graph = build(shot_list, budget=budget)
    compile_ms = (time.monotonic() - t_compile) * 1000
    node_count = len(graph.nodes)
    print(f"  Graph compiled in {_ms(compile_ms)} ({node_count} nodes, {len(shot_list.shots)} shot(s))")

    # ---- 4. Run the graph with memory probing ----
    print("\n--- Running graph (loading models + executing ops) ---")
    from app.rfir.executor.engine import run_graph

    with tempfile.TemporaryDirectory(prefix="rfir-bench-") as tmpdir:
        ram_before_graph = proc.memory_info().rss / 1048576
        mem_before = mem_sample(device)

        t_graph = time.monotonic()
        ctx = run_graph(graph, job_id="bench-001", output_dir=tmpdir, budget=budget)
        total_wall_ms = (time.monotonic() - t_graph) * 1000

        mem_after = mem_sample(device)
        ram_after_graph = proc.memory_info().rss / 1048576

    # ---- 5. Print per-op breakdown ----
    print(f"\n{'Op':<22} {'Wall':>8} {'RAM Δ':>10} {'Peak VRAM':>12}")
    print("-" * 56)
    for m in ctx.node_metrics:
        print(
            f"  {m.op:<20} {_ms(m.wall_ms):>8} "
            f"{'+' if m.ram_delta_mb >= 0 else ''}{_mb(m.ram_delta_mb):>9} "
            f"{_mb(m.peak_vram_mb):>11}"
        )

    # ---- 6. Summary ----
    print("\n" + "=" * 62)
    print("  Summary")
    print("=" * 62)
    print(f"  Total pipeline latency:  {_ms(total_wall_ms)}")
    print(f"  Graph compile latency:   {_ms(compile_ms)}")
    print(f"  RAM before graph run:    {_mb(ram_before_graph)}")
    print(f"  RAM after graph run:     {_mb(ram_after_graph)}  (+{_mb(ram_after_graph - ram_before_graph)})")
    print(f"  Peak VRAM (job):         {_mb(ctx.peak_vram_mb)}")
    print(f"  Device:                  {ctx.device.upper()}")
    print(f"  Tier distribution:       {ctx.tier_distribution}")
    print(f"  Cost estimate:           ${ctx.cost_estimate_usd():.6f}")
    print(f"  Artifacts:               {list(ctx.artifacts.keys())}")

    # ---- 7. Prometheus snapshot ----
    from app.rfir.metrics import registry
    registry.record_job(ctx)
    print("\n--- Prometheus /metrics snapshot ---")
    print(registry.render_prometheus())

    # ---- 8. JSON dump for CI / further analysis ----
    report = ctx.to_metrics_dict()
    report["compile_ms"] = compile_ms
    report["total_pipeline_ms"] = total_wall_ms
    report["ram_before_graph_mb"] = ram_before_graph
    report["ram_after_graph_mb"] = ram_after_graph
    outfile = os.path.join(tempfile.gettempdir(), "rfir_benchmark_report.json")
    with open(outfile, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\nFull JSON report written to: {outfile}")


if __name__ == "__main__":
    main()
