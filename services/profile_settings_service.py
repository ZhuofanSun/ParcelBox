"""Device-level profile settings and avatar persistence."""

from __future__ import annotations

import base64
import binascii
import mimetypes
import time
from pathlib import Path

from config import config
from data.event_store import EventStore


class ProfileSettingsService:
    """Persist single-device profile metadata and avatar files."""

    _MIME_EXTENSION_MAP = {
        "image/webp": ".webp",
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/gif": ".gif",
    }

    def __init__(self, event_store: EventStore) -> None:
        self._event_store = event_store
        self._project_root = Path(__file__).resolve().parent.parent
        snapshot_dir = Path(config.storage.snapshot_dir)
        if not snapshot_dir.is_absolute():
            snapshot_dir = self._project_root / snapshot_dir
        self._assets_dir = snapshot_dir.parent / "assets"

    def get_profile(self) -> dict:
        """Return current device profile metadata with avatar URL if present."""
        profile = self._event_store.get_device_profile()
        avatar_path = self._avatar_path_from_profile(profile)
        has_avatar = avatar_path is not None and avatar_path.exists()
        avatar_updated_at = profile.get("avatar_updated_at")
        avatar_url = None
        if has_avatar:
            version = int(float(avatar_updated_at) * 1000) if isinstance(avatar_updated_at, (int, float)) else 0
            avatar_url = f"/api/settings/profile/avatar?v={version}"

        return {
            "name": profile["name"],
            "role": profile["role"],
            "avatar_url": avatar_url,
            "avatar_updated_at": avatar_updated_at,
            "has_avatar": has_avatar,
            "updated_at": profile.get("updated_at"),
        }

    def update_profile(self, *, name: str | None = None, role: str | None = None) -> dict:
        """Update device profile text fields."""
        self._event_store.upsert_device_profile(name=name, role=role)
        return self.get_profile()

    def set_avatar_from_data_url(self, data_url: str) -> dict:
        """Decode an uploaded avatar data URL and persist it on disk."""
        media_type, image_bytes = self._decode_image_data_url(data_url)
        extension = self._MIME_EXTENSION_MAP[media_type]
        self._assets_dir.mkdir(parents=True, exist_ok=True)

        profile = self._event_store.get_device_profile()
        old_avatar_path = self._avatar_path_from_profile(profile)
        target_path = self._assets_dir / f"profile_avatar{extension}"
        temporary_path = target_path.with_suffix(f"{target_path.suffix}.tmp")
        temporary_path.write_bytes(image_bytes)
        temporary_path.replace(target_path)

        if old_avatar_path is not None and old_avatar_path != target_path and old_avatar_path.exists():
            old_avatar_path.unlink(missing_ok=True)

        stored_relative_path = self._to_storage_path(target_path)
        self._event_store.upsert_device_profile(
            avatar_path=stored_relative_path,
            avatar_updated_at=time.time(),
        )
        return self.get_profile()

    def clear_avatar(self) -> dict:
        """Delete the stored custom avatar and revert to initials fallback."""
        profile = self._event_store.get_device_profile()
        avatar_path = self._avatar_path_from_profile(profile)
        if avatar_path is not None and avatar_path.exists():
            avatar_path.unlink(missing_ok=True)
        self._event_store.upsert_device_profile(
            avatar_path=None,
            avatar_updated_at=None,
        )
        return self.get_profile()

    def get_avatar_file_path(self) -> Path | None:
        """Return the persisted avatar file path if present."""
        profile = self._event_store.get_device_profile()
        avatar_path = self._avatar_path_from_profile(profile)
        if avatar_path is None or not avatar_path.exists():
            return None
        return avatar_path

    @staticmethod
    def guess_media_type(path: Path) -> str:
        """Return the best-effort media type for a stored avatar file."""
        guessed, _ = mimetypes.guess_type(path.name)
        return guessed or "application/octet-stream"

    def _avatar_path_from_profile(self, profile: dict) -> Path | None:
        raw_path = profile.get("avatar_path")
        if not raw_path:
            return None
        path = Path(str(raw_path))
        if not path.is_absolute():
            path = self._project_root / path
        return path

    def _to_storage_path(self, path: Path) -> str:
        try:
            return path.relative_to(self._project_root).as_posix()
        except ValueError:
            return str(path)

    def _decode_image_data_url(self, data_url: str) -> tuple[str, bytes]:
        if not isinstance(data_url, str) or not data_url.startswith("data:image/"):
            raise ValueError("Avatar must be an image data URL")

        header, separator, encoded = data_url.partition(",")
        if separator != ",":
            raise ValueError("Avatar data URL is invalid")
        if ";base64" not in header:
            raise ValueError("Avatar image must use base64 encoding")

        media_type = header[5:].split(";", 1)[0]
        if media_type not in self._MIME_EXTENSION_MAP:
            raise ValueError("Avatar image type is not supported")

        try:
            image_bytes = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as error:
            raise ValueError("Avatar image data is invalid") from error

        if not image_bytes:
            raise ValueError("Avatar image is empty")

        return media_type, image_bytes
