"""Pluggable artifact store for remote T2V latents (env-configured only).

No folder IDs, paths, or credentials are hardcoded — set via export:

  RENDERFLOW_ARTIFACT_STORE=local|gdrive
  RENDERFLOW_ARTIFACT_ROOT=<local path | Google Drive folder id>
  GOOGLE_APPLICATION_CREDENTIALS=<path to service-account JSON>  # gdrive

URI schemes returned by put():
  local:<relative-key>   e.g. local:job-1/s1_t2v.pt
  gdrive:<file_id>
"""
from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from typing import Protocol

logger = logging.getLogger(__name__)


class ArtifactStore(Protocol):
    def put(self, key: str, src_path: str | Path) -> str:
        """Upload ``src_path`` under ``key``; return a resolvable URI."""
        ...

    def get(self, uri: str, dest_path: str | Path) -> Path:
        """Download ``uri`` to ``dest_path``; return the destination path."""
        ...

    def healthcheck(self) -> bool:
        """True when this store is configured and reachable."""
        ...


def get_artifact_store() -> ArtifactStore:
    """Build a store from env. Unknown/missing store → NullStore (healthcheck False)."""
    kind = (os.environ.get("RENDERFLOW_ARTIFACT_STORE") or "").strip().lower()
    root = (os.environ.get("RENDERFLOW_ARTIFACT_ROOT") or "").strip()
    if kind == "local":
        return LocalArtifactStore(root)
    if kind == "gdrive":
        return GDriveArtifactStore(root)
    return NullArtifactStore(reason=f"RENDERFLOW_ARTIFACT_STORE={kind!r} unset or unsupported")


class NullArtifactStore:
    """Fail-closed placeholder when store env is missing."""

    def __init__(self, reason: str = "not configured") -> None:
        self._reason = reason

    def put(self, key: str, src_path: str | Path) -> str:
        raise RuntimeError(f"artifact store not configured ({self._reason})")

    def get(self, uri: str, dest_path: str | Path) -> Path:
        raise RuntimeError(f"artifact store not configured ({self._reason})")

    def healthcheck(self) -> bool:
        logger.info("artifact store healthcheck: fail (%s)", self._reason)
        return False


class LocalArtifactStore:
    """Filesystem store under RENDERFLOW_ARTIFACT_ROOT (same host / synced volume)."""

    def __init__(self, root: str) -> None:
        self.root = Path(root) if root else Path("")

    def put(self, key: str, src_path: str | Path) -> str:
        if not self.root.parts:
            raise RuntimeError("RENDERFLOW_ARTIFACT_ROOT is required for local store")
        key = key.lstrip("/")
        dest = self.root / key
        dest.parent.mkdir(parents=True, exist_ok=True)
        data = Path(src_path).read_bytes()
        dest.write_bytes(data)
        return f"local:{key}"

    def get(self, uri: str, dest_path: str | Path) -> Path:
        key = _parse_local_uri(uri)
        src = self.root / key
        if not src.is_file():
            raise FileNotFoundError(f"local artifact missing: {src}")
        dest = Path(dest_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(src.read_bytes())
        return dest

    def healthcheck(self) -> bool:
        if not self.root.parts:
            logger.info("artifact store healthcheck: fail (RENDERFLOW_ARTIFACT_ROOT empty)")
            return False
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            probe = self.root / ".renderflow_store_ok"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            logger.info("artifact store healthcheck: ok (local root=%s)", self.root)
            return True
        except Exception as e:
            logger.warning("artifact store healthcheck: fail (local: %s)", e)
            return False


class GDriveArtifactStore:
    """Google Drive folder store. Root = folder id from RENDERFLOW_ARTIFACT_ROOT."""

    def __init__(self, folder_id: str) -> None:
        self.folder_id = folder_id

    def put(self, key: str, src_path: str | Path) -> str:
        service = _gdrive_service()
        name = Path(key).name
        # Nest under folder_id; optional subdirs as Drive folders would be heavier —
        # use flat name with key sanitized for uniqueness.
        safe_name = key.replace("/", "__")
        meta = {
            "name": safe_name or name,
            "parents": [self.folder_id],
        }
        from googleapiclient.http import MediaFileUpload

        media = MediaFileUpload(str(src_path), mimetype="application/octet-stream", resumable=True)
        created = (
            service.files()
            .create(body=meta, media_body=media, fields="id", supportsAllDrives=True)
            .execute()
        )
        file_id = created["id"]
        return f"gdrive:{file_id}"

    def get(self, uri: str, dest_path: str | Path) -> Path:
        file_id = _parse_gdrive_uri(uri)
        service = _gdrive_service()
        dest = Path(dest_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        from googleapiclient.http import MediaIoBaseDownload

        request = service.files().get_media(fileId=file_id, supportsAllDrives=True)
        with dest.open("wb") as fh:
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()
        return dest

    def healthcheck(self) -> bool:
        if not self.folder_id:
            logger.info("artifact store healthcheck: fail (RENDERFLOW_ARTIFACT_ROOT folder id empty)")
            return False
        if not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
            logger.info(
                "artifact store healthcheck: fail (GOOGLE_APPLICATION_CREDENTIALS not set)"
            )
            return False
        try:
            service = _gdrive_service()
            service.files().get(
                fileId=self.folder_id,
                fields="id,name",
                supportsAllDrives=True,
            ).execute()
            logger.info("artifact store healthcheck: ok (gdrive folder configured)")
            return True
        except Exception as e:
            logger.warning("artifact store healthcheck: fail (gdrive: %s)", e)
            return False


def _parse_local_uri(uri: str) -> str:
    if uri.startswith("local:"):
        return uri[len("local:") :]
    if uri.startswith("file:"):
        from urllib.parse import urlparse
        from urllib.request import url2pathname

        return url2pathname(urlparse(uri).path)
    raise ValueError(f"unsupported local artifact URI: {uri!r}")


def _parse_gdrive_uri(uri: str) -> str:
    if uri.startswith("gdrive:"):
        return uri[len("gdrive:") :]
    raise ValueError(f"unsupported gdrive artifact URI: {uri!r}")


def _gdrive_service():
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
    except ImportError as e:
        raise RuntimeError(
            "gdrive store requires google-api-python-client and google-auth "
            "(pip/poetry install). Original: %s" % e
        ) from e

    creds_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if not creds_path:
        raise RuntimeError("GOOGLE_APPLICATION_CREDENTIALS is required for gdrive store")
    scopes = ["https://www.googleapis.com/auth/drive"]
    creds = service_account.Credentials.from_service_account_file(creds_path, scopes=scopes)
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def download_to_temp(store: ArtifactStore, uri: str, suffix: str = ".pt") -> Path:
    """Download URI into a temp file; caller owns cleanup."""
    fd, name = tempfile.mkstemp(suffix=suffix, prefix="rfir_artifact_")
    os.close(fd)
    path = Path(name)
    try:
        return store.get(uri, path)
    except Exception:
        path.unlink(missing_ok=True)
        raise
