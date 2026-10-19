import hashlib
import secrets
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api_keys.models import APIKey
from app.models import User

KEY_PREFIX = "ddb_live_"
SCROBBLE_WRITE_SCOPE = "scrobble:write"


def _hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def generate_api_key() -> tuple[str, str, str]:
    """Return (raw secret, public prefix, stored hash)."""
    raw_key = f"{KEY_PREFIX}{secrets.token_urlsafe(32)}"
    return raw_key, raw_key[:24], _hash_key(raw_key)


async def authenticate_api_key(db: AsyncSession, raw_key: str, *, required_scope: str | None = None) -> User | None:
    if not raw_key.startswith(KEY_PREFIX):
        return None
    result = await db.execute(select(APIKey).where(APIKey.key_prefix == raw_key[:24], APIKey.revoked_at.is_(None)))
    api_key = result.scalar_one_or_none()
    if api_key is None or not secrets.compare_digest(api_key.key_hash, _hash_key(raw_key)):
        return None
    user_result = await db.execute(select(User).where(User.id == api_key.user_id))
    user = user_result.scalar_one_or_none()
    if user is None or not user.is_active:
        return None
    if required_scope and required_scope not in api_key.scopes.split():
        return None
    api_key.last_used_at = datetime.now(timezone.utc)
    await db.commit()
    return user
