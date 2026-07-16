"""Vendored RIFE 4.6 architecture.

The upstream MIT model source (IFNet + backward warp), inference-only, committed
to the repo. See ../NOTICE.md for provenance and the two local modifications.

If this package is missing or the LFS weights aren't pulled, `RIFEModel.load()`
raises and the rife_interpolate op falls back to blend interpolation (no
pipeline regression).
"""
