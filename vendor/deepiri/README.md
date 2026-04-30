# Vendored Deepiri Code

This directory contains minimal vendored copies of Deepiri packages used by Renderflow.

## Contents

| Package | Source | Status |
|---------|--------|--------|
| `deepiri-shared-utils` | Not yet available | Placeholder |

## Usage

Prefer using Poetry path dependencies (`deepiri-gpu-utils`) over vendoring. Only vendor when:
1. No package exists upstream
2. A specific fix is required and upstream PR is pending
3. The snippet is <50 lines and has no proper home

## Adding new vendored code

1. Copy minimal files to `vendor/deepiri/<package>/`.
2. Add provenance header:
   ```rust
   // Renderflow adaptation: <original source>, commit <hash>
   // Original: <path>
   ```
3. Add entry to this file with date and commit hash.
4. Prefer thin adapters in `core/` over editing vendored files.