"""Vendored RIFE 4.6 architecture (populated by scripts/vendor_rife.py).

This package is intentionally empty in version control — run the vendoring
script once to fetch the upstream MIT-licensed model source (IFNet + warp +
Model wrapper) and its LICENSE into this directory at a pinned commit.

Until it's populated, `RIFEModel.load()` raises and the rife_interpolate op
falls back to the blend interpolation (no pipeline regression).
"""
