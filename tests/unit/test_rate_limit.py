"""Unit test: that limiter.limit(...) actually enforces a limit (against a
throwaway Limiter/app, not the real shared one -- see tests/conftest.py's
_disable_rate_limiting).
"""

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from slowapi import Limiter


def test_limiter_limit_enforces_the_configured_rate() -> None:
    """A route decorated with limiter.limit(...) 429s once its limit is exceeded."""
    throwaway_limiter = Limiter(key_func=lambda request: "fixed-test-key")
    app = FastAPI()

    @app.get("/limited")
    @throwaway_limiter.limit("1/minute")
    async def limited(request: Request) -> dict[str, bool]:
        return {"ok": True}

    client = TestClient(app)
    assert client.get("/limited").status_code == 200
    assert client.get("/limited").status_code == 429
