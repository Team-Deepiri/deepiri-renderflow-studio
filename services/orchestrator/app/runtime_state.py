from __future__ import annotations

from app.config import Settings

_settings: Settings | None = None


def set_settings(s: Settings) -> None:
    global _settings
    _settings = s


def get_settings() -> Settings:
    if _settings is None:
        return Settings()
    return _settings
