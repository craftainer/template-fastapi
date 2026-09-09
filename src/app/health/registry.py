"""Registry of health checks, run together to answer readiness."""

import asyncio
from functools import lru_cache

from app.config import get_settings
from app.health.base import HealthCheck, HealthCheckResult
from app.health.checks import (
    DatabaseHealthCheck,
    MockHealthCheck,
    OIDCHealthCheck,
    RedisHealthCheck,
    S3HealthCheck,
)
from crud.models.base import engine


class HealthRegistry:
    """Collects HealthCheck instances and runs them all concurrently."""

    def __init__(self) -> None:
        """Start with an empty set of registered checks."""
        self._checks: list[HealthCheck] = []

    def register(self, check: HealthCheck) -> None:
        """Add a check to be run on the next `run_all`."""
        self._checks.append(check)

    async def run_all(self) -> list[HealthCheckResult]:
        """Run every registered check concurrently and return their results."""
        return list(await asyncio.gather(*(check.check() for check in self._checks)))


@lru_cache
def get_health_registry() -> HealthRegistry:
    """Return the process-wide cached HealthRegistry, with every external service registered.

    MODE=mock registers MockHealthCheck for every service instead of the real checks --
    there's nothing real to reach (see crud.repositories.memory, app.oidc's mock decode path).
    """
    settings = get_settings()
    registry = HealthRegistry()
    if settings.mode == "mock":
        registry.register(MockHealthCheck("database"))
        registry.register(MockHealthCheck("redis"))
        registry.register(MockHealthCheck("s3"))
        registry.register(MockHealthCheck("oidc"))
        return registry
    registry.register(DatabaseHealthCheck(engine))
    registry.register(RedisHealthCheck(settings.redis_url))
    registry.register(
        S3HealthCheck(settings.s3_endpoint_url, settings.s3_access_key, settings.s3_secret_key)
    )
    registry.register(OIDCHealthCheck(settings.oidc_issuer_url))
    return registry
