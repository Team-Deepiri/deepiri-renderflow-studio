# Deepiri Vendored Modules

This folder stores copied/adapted code from Deepiri packages.

## Policy

- Do not import these packages directly across repository boundaries.
- Copy source and adapt locally for Renderflow requirements.
- Keep provenance metadata in each file header.

## Modules

- `gpu-utils/`: GPU detection and runtime capability helpers.
- `helox/`: device/runtime management utilities.
- `cyrex/`: queueing and orchestration patterns.
- `synapse/`: event contract models.
- `sugarglider/`: reserved for utility imports when located.

`sugarglider` source path was not found in current workspace and remains pending discovery.
