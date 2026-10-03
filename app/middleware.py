from __future__ import annotations

from fastapi import HTTPException
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.security import (
    AUTH_RATE_LIMITS,
    _RateLimitBucket,
    client_key,
    get_or_create_csrf_token,
    rate_limiter,
    require_csrf,
    set_csrf_cookie,
)

templates = Jinja2Templates(directory="app/templates")

# Auth form POSTs that should get a rendered HTML error page instead of
# plain text / JSON when CSRF validation fails.
AUTH_FORM_PATHS = {"/login", "/register", "/forgot-password"}


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
            # BaseHTTPMiddleware consumes the body stream. Cache it and replay
            # so downstream Form(...) / require_csrf can still read the form.
            body = await request.body()

            async def receive():
                return {"type": "http.request", "body": body, "more_body": False}

            request = Request(request.scope, receive)
            request.state.csrf_token = token

            try:
                await require_csrf(request)
            except HTTPException as exc:
                response = self._csrf_failure_response(request, path, token, exc)
                if should_set_cookie:
                    set_csrf_cookie(response, token)
                return response

        response = await call_next(request)

        if should_set_cookie:
            set_csrf_cookie(response, token)

        return response

    def _csrf_failure_response(
        self,
        request: Request,
        path: str,
        token: str,
        exc: HTTPException,
    ) -> Response:
        """Return a pretty HTML form error for auth pages; plain text otherwise."""
        message = (
            "Security check failed. Please refresh the page and try again."
        )

        if path == "/login":
            response = templates.TemplateResponse(
                request=request,
                name="login.html",
                context={
                    "request": request,
                    "error": message,
                    "username": "",
                },
                status_code=403,
            )
            # Ensure the template still has a valid token for the next attempt.
            request.state.csrf_token = token
            return response

        if path == "/register":
            response = templates.TemplateResponse(
                request=request,
                name="register.html",
                context={
                    "request": request,
                    "error": message,
                },
                status_code=403,
            )
            request.state.csrf_token = token
            return response

        if path == "/forgot-password":
            response = templates.TemplateResponse(
                request=request,
                name="forgot_password.html",
                context={
                    "request": request,
                    "error": message,
                    "username": "",
                },
                status_code=403,
            )
            request.state.csrf_token = token
            return response

        return Response(
            content=exc.detail or "CSRF validation failed.",
            status_code=exc.status_code,
            media_type="text/plain",
        )
