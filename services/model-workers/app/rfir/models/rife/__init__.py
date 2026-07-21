"""Vendored RIFE 4.6 frame interpolation.

`RIFEModel` is RenderFlow's integration wrapper; the actual network lives in
`_vendor/` (committed upstream MIT source). See NOTICE.md.
"""
from app.rfir.models.rife.rife_model import RIFEModel

__all__ = ["RIFEModel"]
