"""Integration test: each concrete health check against its real stack service."""

from app.config import get_settings
from app.health.checks import DatabaseHealthCheck, OIDCHealthCheck, RedisHealthCheck, S3HealthCheck
from crud.models.base import engine


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
