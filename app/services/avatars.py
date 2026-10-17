"""Local avatar file storage: validate, resize, save, delete."""

from __future__ import annotations

import io
import re
import secrets
from pathlib import Path

from fastapi import UploadFile
from PIL import Image, UnidentifiedImageError

from app.config import settings

# Public URL prefix mounted in main.py
AVATAR_URL_PREFIX = "/media/avatars"

# New uploads: opaque names. Legacy: {user_id}.webp from first implementation.
_OPAQUE_NAME = re.compile(r"^[a-zA-Z0-9_-]{16,64}\.webp$")
_LEGACY_NAME = re.compile(r"^[0-9]+\.webp$")

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


def _is_safe_avatar_filename(name: str) -> bool:
    return bool(_OPAQUE_NAME.match(name) or _LEGACY_NAME.match(name))


def is_local_avatar_url(url: str | None) -> bool:
    """True for server-stored avatars (opaque or legacy user_id.webp)."""
    if not url:
        return False
    if not url.startswith(f"{AVATAR_URL_PREFIX}/"):
        return False
    name = url[len(AVATAR_URL_PREFIX) + 1 :]
    # Reject path traversal or nested paths
    if "/" in name or "\\" in name or name in (".", ".."):
        return False
    return _is_safe_avatar_filename(name)


def _filename_from_url(url: str) -> str | None:
    if not is_local_avatar_url(url):
        return None
    return url[len(AVATAR_URL_PREFIX) + 1 :]


def delete_local_avatar_by_url(url: str | None) -> None:
    """Remove file for a stored local avatar URL. No-op if not local/safe."""
    name = _filename_from_url(url) if url else None
    if not name:
        return
    path = settings.avatar_dir_path / name
    try:
        resolved = path.resolve()
        base = settings.avatar_dir_path.resolve()
        if base not in resolved.parents and resolved.parent != base:
            return
    except OSError:
        return
    if path.is_file():
        path.unlink()


def _new_opaque_filename() -> str:
    return f"{secrets.token_urlsafe(24)}.webp"


async def save_avatar_upload(upload: UploadFile, *, replace_url: str | None = None) -> str:
    """Validate and store upload; return public URL path with opaque filename."""
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
    filename = _new_opaque_filename()
    while not _OPAQUE_NAME.match(filename):
        filename = _new_opaque_filename()

    dest = settings.avatar_dir_path / filename
    tmp = dest.with_suffix(".tmp.webp")
    try:
        image.save(tmp, format="WEBP", quality=85, method=4)
        tmp.replace(dest)
    except OSError as exc:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
        raise AvatarError("Could not save avatar to disk.") from exc

    if replace_url and is_local_avatar_url(replace_url):
        old_name = _filename_from_url(replace_url)
        if old_name and old_name != filename:
            delete_local_avatar_by_url(replace_url)

    return f"{AVATAR_URL_PREFIX}/{filename}"
