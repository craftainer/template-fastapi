"""Integration test: each concrete health check against its real stack service.

Also covers /health/ready end-to-end, via app.main's actually-wired registry.
"""

from fastapi.testclient import TestClient

from app.config import get_settings
from app.health_checks import DatabaseHealthCheck, OIDCHealthCheck, RedisHealthCheck, S3HealthCheck
from app.main import app
from crud.models.base import engine

client = TestClient(app)


async def test_database_check_against_real_postgres() -> None:
    """DatabaseHealthCheck reports healthy against the live postgres stack service."""
    result = await DatabaseHealthCheck(engine).check()
    assert result.healthy is True


async def test_redis_check_against_real_redis() -> None:
    """RedisHealthCheck reports healthy against the live redis stack service."""
    result = await RedisHealthCheck(get_settings().redis_url).check()
    assert result.healthy is True


async def test_s3_check_against_real_s3() -> None:
    """S3HealthCheck reports healthy against the live s3 (RustFS) stack service."""
    settings = get_settings()
    result = await S3HealthCheck(
        settings.s3_endpoint_url, settings.s3_access_key, settings.s3_secret_key
    ).check()
    assert result.healthy is True


async def test_oidc_check_against_real_keycloak() -> None:
    """OIDCHealthCheck reports healthy against the live keycloak stack service."""
    result = await OIDCHealthCheck(get_settings().oidc_issuer_url).check()
    assert result.healthy is True


def test_ready_reports_every_stack_service_healthy() -> None:
    """GET /health/ready returns 200 with every real external service healthy."""
    response = client.get("/health/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert set(body["checks"]) == {"database", "redis", "s3", "oidc"}
    assert all(check["healthy"] for check in body["checks"].values())
