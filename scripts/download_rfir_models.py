#!/usr/bin/env python3
"""Download RFIR model weights to RENDERFLOW_MODELS_DIR.

Disk is a working set, not a prepaid catalog. By default this installs the
`core` + `t2i` packs — everything a Tier A job needs — and nothing else. The
executor fetches T2V and SAM on demand the first time a compiled graph names
those roles, so a machine that never renders video never stores CogVideoX.

Usage:
    export RENDERFLOW_MODELS_DIR=$HOME/renderflow-models
    pip install huggingface_hub
    python scripts/download_rfir_models.py                 # core + t2i (~14 GB)
    python scripts/download_rfir_models.py --pack all      # everything (~24 GB)
    python scripts/download_rfir_models.py --pack core,t2v
    python scripts/download_rfir_models.py --t2i-model sdxl-turbo-fp16
    python scripts/download_rfir_models.py --dry-run

FLUX.1-schnell is gated — accept the license on HuggingFace then run:
    huggingface-cli login
before downloading. The script skips it gracefully if you're not logged in.

Spec: docs/superpowers/specs/2026-08-21-rfir-role-residency-design.md
"""
from __future__ import annotations

import argparse
import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO_ROOT, "services", "model-workers"))

from app.rfir.models.fetcher import (  # noqa: E402
    DEFAULT_PACKS,
    PACKS,
    artifact_bytes,
    is_resident,
    plan_downloads,
)
from app.rfir.models.registry import ModelManifest  # noqa: E402
from app.rfir.models.residency import DEFAULT_T2I_MODEL_ID  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--pack",
        default=",".join(DEFAULT_PACKS),
        help=(
            f"comma-separated packs to install: {', '.join(PACKS)}, or 'all'. "
            f"Default: {','.join(DEFAULT_PACKS)}"
        ),
    )
    parser.add_argument(
        "--t2i-model",
        default=os.environ.get("RENDERFLOW_RFIR_T2I_MODEL") or DEFAULT_T2I_MODEL_ID,
        help=f"which T2I backend to install (one, never both). Default: {DEFAULT_T2I_MODEL_ID}",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print what would be downloaded and exit",
    )
    return parser.parse_args(argv)


def download(
    snapshot_download,
    models_dir: str,
    manifest: ModelManifest,
) -> None:
    dest = os.path.join(models_dir, manifest.local_dir)
    if is_resident(models_dir, manifest.local_dir):
        print(f"  skip  {manifest.local_dir}")
        return
    print(f"  fetch {manifest.repo} → {manifest.local_dir}")
    try:
        snapshot_download(
            repo_id=manifest.repo,
            local_dir=dest,
            allow_patterns=list(manifest.allow_patterns) or None,
        )
        print(f"  done  {manifest.local_dir}")
    except Exception as exc:
        msg = str(exc)
        if "401" in msg or "gated" in msg.lower() or "access" in msg.lower():
            print(f"  skip  {manifest.local_dir} (gated — run: huggingface-cli login, then retry)")
        else:
            print(f"  fail  {manifest.local_dir}: {exc}")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    models_dir = os.environ.get("RENDERFLOW_MODELS_DIR")
    if not models_dir:
        print(
            "RENDERFLOW_MODELS_DIR is not set.\n"
            "Run: export RENDERFLOW_MODELS_DIR=$HOME/renderflow-models",
            file=sys.stderr,
        )
        return 1

    packs = [p.strip() for p in args.pack.split(",") if p.strip()]
    try:
        plan = plan_downloads(packs, t2i_model_id=args.t2i_model)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    predicted = sum(artifact_bytes(m) for m in plan)
    print(f"Models root: {models_dir}")
    print(f"Packs: {','.join(packs)}   T2I: {args.t2i_model}")
    print(f"Planned: {len(plan)} artifact(s), ~{predicted / 1e9:.0f} GB if none are present\n")

    if args.dry_run:
        for manifest in plan:
            state = "present" if is_resident(models_dir, manifest.local_dir) else "missing"
            size = artifact_bytes(manifest) / 1e9
            print(f"  {state:8} {manifest.local_dir:26} {manifest.repo}  (~{size:.1f} GB)")
        return 0

    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        print("huggingface_hub is required: pip install huggingface_hub", file=sys.stderr)
        return 1

    os.makedirs(models_dir, exist_ok=True)
    for manifest in plan:
        download(snapshot_download, models_dir, manifest)

    print("\nDone. T2V and SAM are fetched on demand when a graph needs them.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
