"""Compatibility ASGI entrypoint for `uvicorn app.api.main:app`."""

from app.main import app

__all__ = ["app"]
