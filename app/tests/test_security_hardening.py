
import pytest

from app.config import Settings
from app.routers.auth import (
    BCRYPT_MAX_BYTES,
    MIN_PASSWORD_BYTES,
    get_password_hash,
    validate_password,
    verify_password,
)
from app.security import (
    _RateLimitBucket,
    InMemoryRateLimiter,
    create_csrf_token,
    validate_csrf_token,
)


def test_password_validation_rejects_short_and_overlong_passwords():
    assert validate_password("a" * (MIN_PASSWORD_BYTES - 1))
    assert validate_password("a" * BCRYPT_MAX_BYTES) is None
    assert validate_password("a" * (BCRYPT_MAX_BYTES + 1))


def test_password_validation_counts_utf8_bytes():
    password = "é" * (BCRYPT_MAX_BYTES // 2)
    assert len(password.encode("utf-8")) == BCRYPT_MAX_BYTES
    assert validate_password(password) is None
    assert validate_password(password + "é")


def test_password_hash_does_not_truncate_long_input():
    with pytest.raises(ValueError):
        get_password_hash("a" * (BCRYPT_MAX_BYTES + 1))


def test_password_hash_and_verify_work_for_supported_password():
    password = "correct-horse-123"
    hashed = get_password_hash(password)
    assert verify_password(password, hashed)
    assert not verify_password(password + "-wrong", hashed)


def test_csrf_tokens_are_signed_and_tamper_evident():
    token = create_csrf_token()
    assert validate_csrf_token(token)

    nonce, signature = token.rsplit(".", 1)
    assert not validate_csrf_token(f"{nonce}x.{signature}")
    assert not validate_csrf_token(f"{nonce}.{signature}x")
    assert not validate_csrf_token("not-a-token")


def test_rate_limiter_blocks_after_limit_and_allows_after_window():
    limiter = InMemoryRateLimiter()
    bucket = _RateLimitBucket(limit=2, window_seconds=10)

    assert limiter.allow("client", bucket, now=100.0)
    assert limiter.allow("client", bucket, now=101.0)
    assert not limiter.allow("client", bucket, now=102.0)
    assert limiter.allow("client", bucket, now=111.0)


def test_production_settings_require_secure_cookies_and_debug_off():
    with pytest.raises(ValueError, match="COOKIE_SECURE"):
        Settings(
            SECRET_KEY="test-secret",
            ENVIRONMENT="production",
            DEBUG=False,
            COOKIE_SECURE=False,
        )

    with pytest.raises(ValueError, match="DEBUG"):
        Settings(
            SECRET_KEY="test-secret",
            ENVIRONMENT="production",
            DEBUG=True,
            COOKIE_SECURE=True,
        )

    settings = Settings(
        SECRET_KEY="test-secret",
        ENVIRONMENT="production",
        DEBUG=False,
        COOKIE_SECURE=True,
    )
    assert settings.COOKIE_SECURE is True

@pytest.mark.asyncio
async def test_security_middleware_enforces_csrf_and_sets_cookie():
    from fastapi import FastAPI
    from fastapi.responses import PlainTextResponse
    from httpx import ASGITransport, AsyncClient
    from app.middleware import SecurityMiddleware

    test_app = FastAPI()
    test_app.add_middleware(SecurityMiddleware)

    @test_app.post("/mutate")
    async def mutate():
        return PlainTextResponse("ok")

    from app.security import rate_limiter
    rate_limiter.clear()

    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/missing")
        assert response.status_code == 404
        csrf_token = ac.cookies["csrf_token"]

        rejected = await ac.post("/mutate")
        assert rejected.status_code == 403

        accepted = await ac.post(
            "/mutate",
            headers={"X-CSRF-Token": csrf_token},
        )
        assert accepted.status_code == 200
        assert accepted.text == "ok"


@pytest.mark.asyncio
async def test_security_middleware_rate_limits_login_path():
    from fastapi import FastAPI
    from fastapi.responses import PlainTextResponse
    from httpx import ASGITransport, AsyncClient
    from app.middleware import SecurityMiddleware
    from app.security import rate_limiter

    test_app = FastAPI()
    test_app.add_middleware(SecurityMiddleware)

    @test_app.post("/login")
    async def login_probe():
        return PlainTextResponse("ok")

    rate_limiter.clear()

    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        await ac.get("/missing")
        csrf_token = ac.cookies["csrf_token"]
        headers = {"X-CSRF-Token": csrf_token}
        for _ in range(10):
            response = await ac.post("/login", headers=headers)
            assert response.status_code == 200

        limited = await ac.post("/login", headers=headers)
        assert limited.status_code == 429
        assert limited.headers["Retry-After"]
