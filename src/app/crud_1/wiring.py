"""Wires `craftainer_tool_crud` to this app: session factory, config, and rate limiting.

Importing this module installs the crud config (built from `Settings`) and the
app's session factory via `craftainer_tool_crud.config.configure`, and exposes
`bulk_rate_limit`, the decorator every resource router passes to
`build_resource_router(bulk_rate_limit=...)`. Resource modules import it, so the
config is always installed before any router is built or request served -- even
for tests that import a resource module without `app.main`.
"""

from app.config import get_settings
from app.db import session_factory
from app.rate_limit import limiter
from craftainer_tool_crud.config import CrudConfig, MQTTConfig, configure
from craftainer_tool_crud.controllers.crud_router import RateLimit

_settings = get_settings()

configure(
    CrudConfig(
        use_memory=_settings.mode == "mock",
        bulk_action_max_matched=_settings.bulk_action_max_matched,
        sse_keepalive_seconds=_settings.sse_keepalive_seconds,
        mqtt=MQTTConfig(
            host=_settings.mqtt_host,
            port=_settings.mqtt_port,
            keepalive_seconds=_settings.mqtt_keepalive_seconds,
            username=_settings.mqtt_username,
            password=_settings.mqtt_password,
            use_tls=_settings.mqtt_use_tls,
        ),
    ),
    session_factory,
)

bulk_rate_limit: RateLimit = limiter.limit(_settings.rate_limit_bulk_action)
