"""This app's health registry, built from `Settings` -- the checks themselves live in
`craftainer_tool_observability.health.checks`.

Also MockHealthCheck, a network-free always-healthy stand-in used when MODE=mock.
It is excluded from the coverage gate for the same MODE-only reason as
craftainer_tool_crud.repositories.memory -- see its module docstring.
"""

from functools import lru_cache

import boto3

from app.config import get_settings
from app.db import engine
from craftainer_tool_observability.health.base import HealthCheckResult
from craftainer_tool_observability.health.checks.http import HTTPCheck
from craftainer_tool_observability.health.checks.postgres import PostgresCheck
from craftainer_tool_observability.health.checks.redis import RedisCheck
from craftainer_tool_observability.health.checks.s3 import S3Check
from craftainer_tool_observability.health.registry import HealthRegistry


class MockHealthCheck:  # pragma: no cover -- see module docstring
    """Always-healthy check for MODE=mock, standing in for a real external service."""

    def __init__(self, name: str) -> None:
        """Bind this check to the name of the service it stands in for."""
        self.name = name

    async def check(self) -> HealthCheckResult:
        """Report healthy without touching the network."""
        return HealthCheckResult(self.name, healthy=True, detail="mocked")


@lru_cache
def get_health_registry() -> HealthRegistry:
    """Return the process-wide cached HealthRegistry, with every external service registered.

    MODE=mock registers MockHealthCheck for every service instead of the real checks --
    there's nothing real to reach (see craftainer_tool_crud.repositories.memory, app.oidc's mock
    decode path).
    """
    settings = get_settings()
    registry = HealthRegistry()
    if settings.mode == "mock":
        registry.register(MockHealthCheck("database"))
        registry.register(MockHealthCheck("redis"))
        registry.register(MockHealthCheck("s3"))
        registry.register(MockHealthCheck("oidc"))
        return registry
    registry.register(PostgresCheck(engine, name="database"))
    registry.register(RedisCheck(settings.redis_url))
    registry.register(
        S3Check(
            boto3.client(
                "s3",
                endpoint_url=settings.s3_endpoint_url,
                aws_access_key_id=settings.s3_access_key,
                aws_secret_access_key=settings.s3_secret_key,
            )
        )
    )
    discovery_url = f"{settings.oidc_issuer_url.rstrip('/')}/.well-known/openid-configuration"
    registry.register(HTTPCheck(discovery_url, name="oidc"))
    return registry
