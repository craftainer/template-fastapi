"""Application settings, sourced entirely from the process environment.

Both `_require_*` validators below are `# pragma: no cover` for tests/e2e
specifically: the live api process only ever starts with a Settings that
already satisfies them (see .devcontainer/compose.yml's MODE=dev/mock), so a
raise from either one would mean the process never came up for tests/e2e to
run against in the first place. tests/unit/test_config.py exercises both
directly and still counts toward its own 95% gate.
"""

from functools import lru_cache
from typing import Literal, Self

from pydantic import Field, computed_field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Mode = Literal["dev", "mock", "production"]


class Settings(BaseSettings):
    """Typed application settings."""

    # No .env file for the app itself: every value below is meant to come
    # from the process environment, which the compose files set directly
    # (see .devcontainer/compose.yml and stack/*/compose.yml) --
    # some pulled straight from a stack service's own env file,
    # some (DATABASE_URL, s3_access_key/s3_secret_key) assembled below
    # from those raw pieces since Compose can't interpolate a value from
    # one env file into another compose file's own env var. See
    # README.md's "Configuration" section.
    # extra="forbid" (not "ignore"): pydantic-settings' environment source only ever
    # reads env vars matching a field's own name/validation_alias (verified in
    # tests/unit/test_config.py::test_unrelated_env_vars_are_not_rejected), so this
    # doesn't catch a typo'd env var like OIDC_AUDIANCE -- that's silently absent from
    # the environment source's output either way, "forbid" or "ignore". It does still
    # guard the constructor-kwargs path (Settings(**mapping) with an unrecognized key,
    # e.g. from a future config-file source) rather than silently accepting it.
    model_config = SettingsConfigDict(extra="forbid")

    app_name: str = "template-fastapi"

    # dev: debugger enabled (see app.main). mock: every external service
    # (Postgres, Redis, S3, OIDC) is replaced with a local/in-memory fake --
    # see app.crud_1.heroes, app.health.registry, app.oidc. production:
    # debugger disabled. Defaults to "dev" to match this template's other
    # defaults (localhost hosts, etc.), which assume local/devcontainer use
    # unless overridden -- see the Dockerfile's runner stage for the
    # production default.
    mode: Mode = "dev"

    # MODE=mock trusts every bearer token's claims and skips every real
    # external service (see oidc.decode_bearer_token) -- a deployment that
    # somehow ends up running it (a misconfigured env, a copy-pasted compose
    # file) would silently bypass auth entirely. Requiring this second,
    # explicitly-named flag means MODE=mock can never be reached by MODE's
    # own default/typo alone; only .devcontainer/compose.yml and CI set it,
    # both already scoped to local/CI use.
    allow_mock_mode: bool = False

    # A bulk PATCH/DELETE with a technically-non-empty but always-true filter (e.g.
    # id__gte=0) would otherwise still match every row -- see
    # app.controllers.crud_actions, which counts matches before applying either
    # action and refuses to proceed above this threshold.
    bulk_action_max_matched: int = 1000

    # app.rate_limit: slowapi limit-expression syntax ("<count>/<period>"). Applied to
    # POST /mock/token and each resource's bulk update/delete routes -- the
    # unauthenticated-or-destructive surface prioritized by the OWASP hardening pass
    # this was added in, not every route (see app.rate_limit's module docstring for
    # why this stays per-route instead of a blanket middleware).
    rate_limit_mock_token: str = "10/minute"  # noqa: S105 -- a rate-limit expression, not a secret
    rate_limit_bulk_action: str = "20/minute"

    # app.maintenance.purge_archived: how old an archived row (see app.models.mixins.
    # Archivable) must be before that out-of-request-path script hard-deletes it.
    # None (the default) disables purge entirely -- this devcontainer-only stack has
    # no scheduler/worker service to invoke it automatically either way (see
    # app.maintenance's own module docstring); a real deployment sets this and wires
    # `python -m app.maintenance` into its own host/k8s CronJob.
    archive_purge_after_days: int | None = None

    postgres_user: str = "app"
    postgres_password: str = "app"  # noqa: S105 -- local Postgres default, not a real secret
    postgres_db: str = "app"
    postgres_host: str = "localhost"
    postgres_port: int = 5432

    s3_endpoint_url: str = "http://localhost:9000"
    s3_access_key: str = Field(default="rustfsadmin", validation_alias="RUSTFS_ACCESS_KEY")
    s3_secret_key: str = Field(default="rustfsadmin", validation_alias="RUSTFS_SECRET_KEY")

    redis_url: str = "redis://localhost:6379/0"

    # app.interfaces.dependency.build_event_sink_provider/build_event_source_provider's
    # real (non-MODE=mock) backend -- see .devcontainer/stack/mqtt/.
    # mqtt_keepalive_seconds is the aiomqtt.Client keepalive passed to both
    # MQTTEventSink and MQTTEventSource. mqtt_username/mqtt_password/mqtt_use_tls
    # default to unset/False -- matching .devcontainer/stack/mqtt/mosquitto.conf's
    # own no-auth/no-TLS local-dev default (see its "Don't" section) -- and are
    # required to be set in production, see _require_mqtt_auth_in_production below.
    mqtt_host: str = "localhost"
    mqtt_port: int = 1883
    mqtt_keepalive_seconds: int = 60
    mqtt_username: str | None = None
    mqtt_password: str | None = None
    mqtt_use_tls: bool = False

    # app.controllers.crud_router's `GET <prefix>/events` SSE route: how often an
    # idle stream sends a `: keep-alive` comment, so intermediary proxies/load
    # balancers don't time out the connection.
    sse_keepalive_seconds: float = 15.0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def database_url(self) -> str:
        """Build the async Postgres DSN from the individual connection pieces."""
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    # OIDC: works with any provider supporting Authorization Code + PKCE, not
    # just Keycloak (see src/app/oidc.py). authorization_url/token_url are
    # static so FastAPI can build the Swagger UI login flow at import time,
    # without a network round trip; the JWKS used to validate tokens is
    # instead discovered lazily from issuer_url (see oidc.py), so unit tests
    # that never authenticate never need network access. audience is left
    # unset outside "production" (see _require_oidc_audience_in_production
    # below): the bundled dev realm's "api" client does not set one.
    oidc_issuer_url: str = "http://localhost:8080/realms/template-fastapi"
    oidc_authorization_url: str = (
        "http://localhost:8080/realms/template-fastapi/protocol/openid-connect/auth"
    )
    # "_token_url" trips ruff's S105 (looks like a hardcoded password); it is a URL.
    oidc_token_url: str = (
        "http://localhost:8080/realms/template-fastapi/protocol/openid-connect/token"  # noqa: S105
    )
    oidc_client_id: str = "api"
    oidc_algorithm: str = "RS256"
    oidc_audience: str | None = None

    @model_validator(mode="after")
    def _require_oidc_audience_in_production(self) -> Self:
        """Refuse to construct production Settings with no audience check configured.

        oidc.decode_bearer_token only verifies the "aud" claim when oidc_audience is
        set, so an unset audience in production would accept a token issued for any
        other client of the same provider. dev/mock stay opt-in (the bundled dev
        Keycloak realm sets no audience mapper), so this only tightens the mode that
        actually faces real traffic.
        """
        if self.mode == "production" and self.oidc_audience is None:  # pragma: no cover
            raise ValueError("oidc_audience must be set when MODE=production")
        return self

    @model_validator(mode="after")
    def _require_allow_mock_mode_flag(self) -> Self:
        """Refuse to construct MODE=mock Settings without the explicit allow_mock_mode flag.

        See allow_mock_mode's own docstring for why this second flag exists.
        """
        if self.mode == "mock" and not self.allow_mock_mode:  # pragma: no cover
            raise ValueError("MODE=mock requires ALLOW_MOCK_MODE=1 to be set")
        return self

    @model_validator(mode="after")
    def _require_non_default_credentials_in_production(self) -> Self:
        """Refuse to construct production Settings with a credential left at its local default.

        postgres_password/s3_access_key/s3_secret_key all default to well-known,
        publicly documented values (see this class's own field defaults above) meant
        for the local/devcontainer stack only -- a production deployment that
        inherits one of them unchanged would be trivially guessable.
        """
        if self.mode == "production":  # pragma: no cover
            defaults = {
                "postgres_password": "app",
                "s3_access_key": "rustfsadmin",
                "s3_secret_key": "rustfsadmin",
            }
            left_at_default = [
                field for field, default in defaults.items() if getattr(self, field) == default
            ]
            if left_at_default:
                raise ValueError(
                    f"{', '.join(left_at_default)} must not be left at their default "
                    "value when MODE=production"
                )
        return self

    @model_validator(mode="after")
    def _require_encrypted_connections_in_production(self) -> Self:
        """Refuse to construct production Settings with a plaintext S3/Redis/Postgres scheme.

        `_require_non_default_credentials_in_production` above only checks whether a
        credential still equals its local default -- it says nothing about whether the
        connection carrying that credential (and the data behind it) is encrypted. An
        operator who sets a real Postgres/Redis/S3 endpoint but leaves it on
        `http://`/`redis://`/`postgresql+asyncpg://` would otherwise send credentials
        and query traffic in cleartext with no startup failure to catch it, unlike
        oidc_issuer_url and MQTT, which already require this below.
        """
        if self.mode == "production":  # pragma: no cover
            insecure = []
            if not self.s3_endpoint_url.startswith("https://"):
                insecure.append("s3_endpoint_url must use https://")
            if not self.redis_url.startswith("rediss://"):
                insecure.append("redis_url must use rediss://")
            if insecure:
                raise ValueError("; ".join(insecure) + " when MODE=production")
        return self

    @model_validator(mode="after")
    def _require_https_oidc_issuer_in_production(self) -> Self:
        """Refuse to construct production Settings with a non-https oidc_issuer_url.

        decode_bearer_token fetches the issuer's OIDC discovery document and JWKS
        over whatever scheme oidc_issuer_url uses -- http:// in production would send
        that (and, for the Authorization Code flow itself, the token exchange) in
        cleartext.
        """
        if self.mode == "production" and not self.oidc_issuer_url.startswith(  # pragma: no cover
            "https://"
        ):
            raise ValueError("oidc_issuer_url must use https:// when MODE=production")
        return self

    @model_validator(mode="after")
    def _require_mqtt_auth_in_production(self) -> Self:
        """Refuse to construct production Settings with an unauthenticated MQTT broker.

        app.interfaces.base.MQTTEventSink/MQTTEventSource connect with no
        credentials/TLS unless these are set, matching mosquitto.conf's own
        no-auth/no-TLS local-dev default (see .devcontainer/stack/mqtt/
        mosquitto.conf's "Don't" section) -- a production broker reachable over
        the network with that default would let anyone read or forge every
        resource's create/update/delete events.
        """
        if self.mode == "production" and (  # pragma: no cover
            not self.mqtt_use_tls or self.mqtt_username is None or self.mqtt_password is None
        ):
            raise ValueError(
                "mqtt_use_tls, mqtt_username, and mqtt_password must all be set "
                "when MODE=production"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide cached Settings instance."""
    return Settings()
