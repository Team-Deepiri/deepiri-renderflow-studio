#!/usr/bin/env bash
# Build Renderflow Studio Tauri desktop release for the current OS.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
DESKTOP="$ROOT/apps/desktop-tauri"
UI="$DESKTOP/ui"
TAURI="$DESKTOP/src-tauri"
OUT="$ROOT/release"

cd "$ROOT"
mkdir -p "$OUT"
rm -rf "$OUT"/*

echo "==> Installing UI dependencies"
npm ci --prefix "$UI"
npm run build --prefix "$UI"

echo "==> Installing Tauri CLI"
npm ci --prefix "$DESKTOP"

echo "==> Generating application icons"
python3 scripts/ci/generate_tauri_icons.py

echo "==> Installing Rust toolchain"
if ! command -v cargo >/dev/null 2>&1; then
  curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
  # shellcheck disable=SC1091
  source "$HOME/.cargo/env"
fi

export CI=true
export CSC_IDENTITY_AUTO_DISCOVERY=false

echo "==> Building Tauri bundle"
cd "$DESKTOP"
npm run tauri -- build

BUNDLE_ROOT="$TAURI/target/release/bundle"
if [[ ! -d "$BUNDLE_ROOT" ]]; then
  echo "Bundle directory not found: $BUNDLE_ROOT" >&2
  find "$TAURI/target" -maxdepth 4 -type d 2>/dev/null || true
  exit 1
fi

case "$(uname -s)" in
  Linux)
  APPIMAGE="$(find "$BUNDLE_ROOT" -type f -name '*.AppImage' | head -1)"
  if [[ -z "$APPIMAGE" ]]; then
    echo "No AppImage found under $BUNDLE_ROOT" >&2
    find "$BUNDLE_ROOT" -type f >&2
    exit 1
  fi
  cp "$APPIMAGE" "$OUT/Renderflow-Studio-latest.AppImage"
  ;;
  Darwin)
  DMG="$(find "$BUNDLE_ROOT" -type f -name '*.dmg' | head -1)"
  if [[ -z "$DMG" ]]; then
    echo "No DMG found under $BUNDLE_ROOT" >&2
    find "$BUNDLE_ROOT" -type f >&2
    exit 1
  fi
  cp "$DMG" "$OUT/Renderflow-Studio-latest.dmg"
  ;;
  MINGW*|MSYS*|CYGWIN*)
  INSTALLER="$(find "$BUNDLE_ROOT" -type f \( -name '*setup*.exe' -o -name '*.exe' \) | head -1)"
  if [[ -z "$INSTALLER" ]]; then
    echo "No Windows installer found under $BUNDLE_ROOT" >&2
    find "$BUNDLE_ROOT" -type f >&2
    exit 1
  fi
  cp "$INSTALLER" "$OUT/Renderflow-Studio-latest-setup.exe"
  ;;
  *)
  echo "Unsupported OS: $(uname -s)" >&2
  exit 1
  ;;
esac

echo "==> Release artifacts"
ls -la "$OUT"
