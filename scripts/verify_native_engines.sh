#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
cargo test --manifest-path core/timeline-engine-rs/Cargo.toml
cargo test --manifest-path core/render-engine-vulkan/Cargo.toml
echo "Native engine crates OK (timeline + render/Vulkan graph + loader)."
