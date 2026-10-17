"""Local avatar file storage: validate, resize, save, delete."""

from __future__ import annotations

import io
from pathlib import Path

from fastapi import UploadFile
from PIL import Image, UnidentifiedImageError

from app.config import settings

# Public URL prefix mounted in main.py
AVATAR_URL_PREFIX = "/media/avatars"

ALLOWED_CONTENT_TYPES = {
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/webp",
    "image/gif",
}


class AvatarError(ValueError):
    """User-facing avatar validation or I/O error."""


def ensure_avatar_dir() -> Path:
    path = settings.avatar_dir_path
    path.mkdir(parents=True, exist_ok=True)
    return path


def avatar_filename(user_id: int) -> str:
    return f"{user_id}.webp"


def avatar_disk_path(user_id: int) -> Path:
    return settings.avatar_dir_path / avatar_filename(user_id)


def avatar_public_url(user_id: int) -> str:
    return f"{AVATAR_URL_PREFIX}/{avatar_filename(user_id)}"


def is_local_avatar_url(url: str | None) -> bool:
    if not url:
        return False
    return url.startswith(f"{AVATAR_URL_PREFIX}/")


def delete_local_avatar(user_id: int) -> None:
    path = avatar_disk_path(user_id)
    if path.is_file():
        path.unlink()


async def save_avatar_upload(user_id: int, upload: UploadFile) -> str:
    """Validate and store upload; return public URL path."""
    content_type = (upload.content_type or "").lower().strip()
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise AvatarError("Avatar must be a JPEG, PNG, WebP, or GIF image.")

    data = await upload.read()
    if not data:
        raise AvatarError("Empty file uploaded.")
    if len(data) > settings.AVATAR_MAX_BYTES:
        max_mb = settings.AVATAR_MAX_BYTES / (1024 * 1024)
        raise AvatarError(f"Avatar must be at most {max_mb:.0f} MB.")

    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except UnidentifiedImageError as exc:
        raise AvatarError("Could not read image file.") from exc

    # Normalize to RGB (drop alpha for consistent WebP)
    if image.mode in ("RGBA", "LA", "P"):
        rgba = image.convert("RGBA")
        background = Image.new("RGB", rgba.size, (23, 23, 23))
        background.paste(rgba, mask=rgba.split()[-1])
        image = background
    elif image.mode != "RGB":
        image = image.convert("RGB")

    max_edge = max(1, settings.AVATAR_MAX_EDGE)
    image.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)

    ensure_avatar_dir()
    dest = avatar_disk_path(user_id)
    # Write to temp then replace for atomicity
    tmp = dest.with_suffix(".tmp.webp")
    try:
        image.save(tmp, format="WEBP", quality=85, method=4)
        tmp.replace(dest)
    except OSError as exc:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
        raise AvatarError("Could not save avatar to disk.") from exc

    return avatar_public_url(user_id)
