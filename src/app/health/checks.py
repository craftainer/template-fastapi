"""Concrete health checks for this app's external services: Postgres, Redis, S3, OIDC.

Also MockHealthCheck, a network-free always-healthy stand-in used when MODE=mock.

Each check's failure branch is `# pragma: no cover` for tests/e2e specifically:
proving it requires actually breaking the live shared Postgres/Redis/S3/Keycloak
that e2e (and other engineers' sessions) depend on, which isn't a trade worth
making for a smoke-test suite -- tests/unit/health/test_checks.py fakes each
client to exercise every failure branch instead, and still counts toward its own
95% gate. MockHealthCheck is excluded from that same run for the same MODE-only
reason as crud.repositories.memory -- see its module docstring.
"""

import asyncio
import logging
from typing import TYPE_CHECKING

import boto3
import httpx
from botocore.exceptions import BotoCoreError, ClientError
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from app.health.base import HealthCheckResult

logger = logging.getLogger(__name__)

# GET /ready is unauthenticated (a k8s-style readiness probe) -- the real
# exception text (which can embed a DSN host/port/credentials, an S3 endpoint,
# or an OIDC issuer's response body) goes only to the logs below, for
# whoever's on call to look up; the HTTP response gets this fixed string
# regardless of which service failed or why.
_UNHEALTHY_DETAIL = "dependency check failed; see server logs"

if TYPE_CHECKING:
    # boto3-stubs[s3] is a dev-only dependency (pyproject.toml) -- not
    # installed in the runner image, so this can't be a runtime import.
    # Safe as a type-only import: local variable annotations (the one use
    # below) aren't evaluated at runtime.
    from mypy_boto3_s3 import S3Client


class DatabaseHealthCheck:
    """Checks that Postgres answers a trivial query through the app's async engine."""

    name = "database"

    def __init__(self, engine: AsyncEngine) -> None:
        """Bind this check to the app's shared async engine."""
        self._engine = engine

    async def check(self) -> HealthCheckResult:
        """Run `SELECT 1` and report whether it succeeded."""
        try:
            async with self._engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        except SQLAlchemyError:  # pragma: no cover -- see module docstring
            logger.exception("Database health check failed")
            return HealthCheckResult(self.name, healthy=False, detail=_UNHEALTHY_DETAIL)
        return HealthCheckResult(self.name, healthy=True)


class RedisHealthCheck:
    """Checks that Redis answers PING."""

    name = "redis"

    def __init__(self, redis_url: str) -> None:
        """Bind this check to the Redis connection URL."""
        self._redis_url = redis_url

    async def check(self) -> HealthCheckResult:
        """PING Redis and report whether it succeeded."""
        client = Redis.from_url(self._redis_url)
        try:
            await client.ping()
        except RedisError:  # pragma: no cover -- see module docstring
            logger.exception("Redis health check failed")
            return HealthCheckResult(self.name, healthy=False, detail=_UNHEALTHY_DETAIL)
        finally:
            await client.aclose()
        return HealthCheckResult(self.name, healthy=True)


class S3HealthCheck:
    """Checks that the S3-compatible endpoint answers a ListBuckets call."""

    name = "s3"

    def __init__(self, endpoint_url: str, access_key: str, secret_key: str) -> None:
        """Bind this check to the S3 endpoint and credentials to connect with."""
        self._endpoint_url = endpoint_url
        self._access_key = access_key
        self._secret_key = secret_key

    def _list_buckets(self) -> None:
        client: S3Client = boto3.client(
            "s3",
            endpoint_url=self._endpoint_url,
            aws_access_key_id=self._access_key,
            aws_secret_access_key=self._secret_key,
        )
        client.list_buckets()

    async def check(self) -> HealthCheckResult:
        """Call ListBuckets in a thread and report whether it succeeded."""
        try:
            await asyncio.to_thread(self._list_buckets)
        except BotoCoreError, ClientError:  # pragma: no cover -- see module docstring
            logger.exception("S3 health check failed")
            return HealthCheckResult(self.name, healthy=False, detail=_UNHEALTHY_DETAIL)
        return HealthCheckResult(self.name, healthy=True)


class MockHealthCheck:  # pragma: no cover -- see module docstring
    """Always-healthy check for MODE=mock, standing in for a real external service."""

    def __init__(self, name: str) -> None:
        """Bind this check to the name of the service it stands in for."""
        self.name = name

    async def check(self) -> HealthCheckResult:
        """Report healthy without touching the network."""
        return HealthCheckResult(self.name, healthy=True, detail="mocked")


class OIDCHealthCheck:
    """Checks that the OIDC provider's discovery document is reachable."""

    name = "oidc"

    def __init__(self, issuer_url: str) -> None:
        """Bind this check to the provider's issuer URL."""
        self._issuer_url = issuer_url

    async def check(self) -> HealthCheckResult:
        """Fetch the discovery document and report whether it succeeded."""
        discovery_url = f"{self._issuer_url.rstrip('/')}/.well-known/openid-configuration"
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                response = await client.get(discovery_url)
                response.raise_for_status()
        except httpx.HTTPError:  # pragma: no cover -- see module docstring
            logger.exception("OIDC health check failed")
            return HealthCheckResult(self.name, healthy=False, detail=_UNHEALTHY_DETAIL)
        return HealthCheckResult(self.name, healthy=True)
