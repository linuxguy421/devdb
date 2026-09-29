from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Deque

from fastapi import HTTPException, Request

from app.config import settings

CSRF_COOKIE_NAME = "csrf_token"
CSRF_HEADER_NAME = "X-CSRF-Token"
CSRF_MAX_AGE_SECONDS = 60 * 60 * 24

# Authentication endpoints are intentionally rate-limited separately from the
# rest of the application. These values are conservative defaults for the
# single-process Docker deployment and can be tuned without changing routes.
AUTH_RATE_LIMITS = {
    "/login": (10, 5 * 60),
    "/register": (5, 10 * 60),
    "/forgot-password": (5, 10 * 60),
}


@dataclass(frozen=True)
class _RateLimitBucket:
    limit: int
    window_seconds: int


class InMemoryRateLimiter:
    """Small process-local limiter for unauthenticated authentication endpoints."""

    def __init__(self) -> None:
        self._attempts: dict[tuple[str, str], Deque[float]] = defaultdict(deque)

    def allow(self, key: str, bucket: _RateLimitBucket, now: float | None = None) -> bool:
        current = time.monotonic() if now is None else now
        cutoff = current - bucket.window_seconds
        attempts = self._attempts[(key, str(bucket.limit), str(bucket.window_seconds))]

        while attempts and attempts[0] <= cutoff:
            attempts.popleft()

        if len(attempts) >= bucket.limit:
            return False

        attempts.append(current)
        return True

    def clear(self) -> None:
        self._attempts.clear()


rate_limiter = InMemoryRateLimiter()


def _csrf_signature(token: str) -> str:
    return hmac.new(
        settings.SECRET_KEY.encode("utf-8"),
        token.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def create_csrf_token() -> str:
    nonce = secrets.token_urlsafe(32)
    return f"{nonce}.{_csrf_signature(nonce)}"


def validate_csrf_token(token: str | None) -> bool:
    if not token or "." not in token:
        return False

    nonce, signature = token.rsplit(".", 1)
    if not nonce or not signature:
        return False

    expected = _csrf_signature(nonce)
    return hmac.compare_digest(signature, expected)


def get_or_create_csrf_token(request: Request) -> tuple[str, bool]:
    token = request.cookies.get(CSRF_COOKIE_NAME)
    if token and validate_csrf_token(token):
        return token, False
    return create_csrf_token(), True


def set_csrf_cookie(response, token: str) -> None:
    response.set_cookie(
        key=CSRF_COOKIE_NAME,
        value=token,
        max_age=CSRF_MAX_AGE_SECONDS,
        httponly=False,
        samesite="lax",
        secure=settings.COOKIE_SECURE,
        path="/",
    )


async def require_csrf(request: Request) -> None:
    if request.method.upper() not in {"POST", "PUT", "PATCH", "DELETE"}:
        return

    cookie_token = request.cookies.get(CSRF_COOKIE_NAME)
    header_token = request.headers.get(CSRF_HEADER_NAME)
    submitted_token = header_token

    if not submitted_token:
        try:
            form = await request.form()
            submitted_token = form.get("csrf_token")
        except Exception:
            submitted_token = None

    if (
        not cookie_token
        or not submitted_token
        or cookie_token != submitted_token
        or not validate_csrf_token(cookie_token)
    ):
        raise HTTPException(status_code=403, detail="CSRF validation failed.")


def client_key(request: Request) -> str:
    # Do not trust X-Forwarded-For here. If a reverse proxy is introduced,
    # rate limiting should be moved to the trusted edge or proxy layer.
    return request.client.host if request.client else "unknown"
