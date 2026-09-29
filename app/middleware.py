from __future__ import annotations

from fastapi import HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from app.security import (
    AUTH_RATE_LIMITS,
    CSRF_COOKIE_NAME,
    _RateLimitBucket,
    client_key,
    get_or_create_csrf_token,
    rate_limiter,
    require_csrf,
    set_csrf_cookie,
)


class SecurityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        path = request.url.path
        method = request.method.upper()
        token, should_set_cookie = get_or_create_csrf_token(request)
        request.state.csrf_token = token

        if method == "POST" and path in AUTH_RATE_LIMITS:
            limit, window = AUTH_RATE_LIMITS[path]
            if not rate_limiter.allow(
                f"{client_key(request)}:{path}",
                _RateLimitBucket(limit, window),
            ):
                response = Response(
                    content="Too many requests. Please try again later.",
                    status_code=429,
                    media_type="text/plain",
                )
                response.headers["Retry-After"] = str(window)
                if should_set_cookie:
                    set_csrf_cookie(response, token)
                return response

        if method in {"POST", "PUT", "PATCH", "DELETE"}:
            try:
                await require_csrf(request)
            except HTTPException as exc:
                response = Response(
                    content=exc.detail or "CSRF validation failed.",
                    status_code=exc.status_code,
                    media_type="text/plain",
                )
                if should_set_cookie:
                    set_csrf_cookie(response, token)
                return response

        response = await call_next(request)

        if should_set_cookie:
            set_csrf_cookie(response, token)

        return response
