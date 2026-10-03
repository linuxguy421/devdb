import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient


@pytest.mark.asyncio
async def test_readyz_returns_ready_when_database_is_reachable(monkeypatch):
    import app.main as main

    class FakeResult:
        pass

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def execute(self, statement):
            assert str(statement) == "SELECT 1"
            return FakeResult()

    monkeypatch.setattr(main, "AsyncSessionLocal", lambda: FakeSession())

    transport = ASGITransport(app=main.app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/readyz")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


@pytest.mark.asyncio
async def test_readyz_returns_503_when_database_is_unavailable(monkeypatch):
    import app.main as main

    class FailingSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def execute(self, statement):
            raise RuntimeError("database unavailable")

    monkeypatch.setattr(main, "AsyncSessionLocal", lambda: FailingSession())

    transport = ASGITransport(app=main.app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/readyz")

    assert response.status_code == 503
    assert response.json() == {"status": "not_ready"}
