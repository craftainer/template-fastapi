"""Unit test: Settings.database_url assembles the async Postgres DSN, plus its
mode-dependent validation (production requires oidc_audience/non-default
credentials/https issuer/authenticated MQTT, mock requires allow_mock_mode).
"""

import pytest
from pydantic import ValidationError

from app.config import Settings

_PRODUCTION_KWARGS: dict[str, object] = {
    "mode": "production",
    "oidc_audience": "api",
    "postgres_password": "real-password",
    "RUSTFS_ACCESS_KEY": "real-access-key",
    "RUSTFS_SECRET_KEY": "real-secret-key",
    "oidc_issuer_url": "https://issuer.example.com/realms/prod",
    "mqtt_use_tls": True,
    "mqtt_username": "real-mqtt-user",
    "mqtt_password": "real-mqtt-password",
    "s3_endpoint_url": "https://s3.example.com",
    "redis_url": "rediss://redis.example.com:6379/0",
}


def test_database_url_assembles_dsn_from_pieces() -> None:
    """database_url combines user/password/host/port/db into one asyncpg DSN."""
    settings = Settings(
        postgres_user="u",
        postgres_password="p",  # noqa: S106 -- test fixture value, not a real secret
        postgres_host="h",
        postgres_port=1234,
        postgres_db="d",
    )
    assert settings.database_url == "postgresql+asyncpg://u:p@h:1234/d"


def test_production_mode_requires_oidc_audience(monkeypatch: pytest.MonkeyPatch) -> None:
    """Settings(mode="production") with no oidc_audience raises ValidationError."""
    monkeypatch.delenv("OIDC_AUDIENCE", raising=False)
    with pytest.raises(ValidationError, match="oidc_audience"):
        Settings(mode="production")


def test_production_mode_with_oidc_audience_succeeds() -> None:
    """A fully-configured production Settings (non-default creds, https issuer) constructs fine."""
    settings = Settings(**_PRODUCTION_KWARGS)  # type: ignore[arg-type]
    assert settings.oidc_audience == "api"


@pytest.mark.parametrize(
    ("field", "default"),
    [
        ("postgres_password", "app"),
        ("RUSTFS_ACCESS_KEY", "rustfsadmin"),
        ("RUSTFS_SECRET_KEY", "rustfsadmin"),
    ],
)
def test_production_mode_rejects_default_credentials(field: str, default: str) -> None:
    """Settings(mode="production") with any credential left at its default raises."""
    kwargs = {**_PRODUCTION_KWARGS, field: default}
    with pytest.raises(ValidationError, match="must not be left at their default"):
        Settings(**kwargs)  # type: ignore[arg-type]


def test_dev_mode_allows_default_credentials() -> None:
    """Settings(mode="dev") (the default) keeps every credential at its local default."""
    settings = Settings()
    assert settings.postgres_password == "app"  # noqa: S105 -- asserting the local default
    assert settings.s3_access_key == "rustfsadmin"


def test_production_mode_requires_https_oidc_issuer() -> None:
    """Settings(mode="production") with an http:// oidc_issuer_url raises."""
    kwargs = {**_PRODUCTION_KWARGS, "oidc_issuer_url": "http://issuer.example.com/realms/prod"}
    with pytest.raises(ValidationError, match="oidc_issuer_url"):
        Settings(**kwargs)  # type: ignore[arg-type]


def test_dev_mode_allows_http_oidc_issuer() -> None:
    """Settings(mode="dev") (the default) keeps the local http:// issuer URL default."""
    assert Settings().oidc_issuer_url.startswith("http://")


@pytest.mark.parametrize(
    "override",
    [
        {"mqtt_use_tls": False},
        {"mqtt_username": None},
        {"mqtt_password": None},
    ],
)
def test_production_mode_requires_authenticated_mqtt(override: dict[str, object]) -> None:
    """Settings(mode="production") with TLS off or no username/password raises."""
    kwargs = {**_PRODUCTION_KWARGS, **override}
    with pytest.raises(ValidationError, match="mqtt_use_tls, mqtt_username, and mqtt_password"):
        Settings(**kwargs)  # type: ignore[arg-type]


def test_dev_mode_allows_unauthenticated_mqtt() -> None:
    """Settings(mode="dev") (the default) keeps the local no-auth/no-TLS MQTT defaults."""
    settings = Settings()
    assert settings.mqtt_use_tls is False
    assert settings.mqtt_username is None
    assert settings.mqtt_password is None


def test_production_mode_requires_https_s3_endpoint() -> None:
    """Settings(mode="production") with an http:// s3_endpoint_url raises."""
    kwargs = {**_PRODUCTION_KWARGS, "s3_endpoint_url": "http://s3.example.com"}
    with pytest.raises(ValidationError, match="s3_endpoint_url"):
        Settings(**kwargs)  # type: ignore[arg-type]


def test_dev_mode_allows_http_s3_endpoint() -> None:
    """Settings(mode="dev") (the default) keeps the local http:// S3 endpoint default."""
    assert Settings().s3_endpoint_url.startswith("http://")


def test_production_mode_requires_encrypted_redis_url() -> None:
    """Settings(mode="production") with a plain redis:// URL raises."""
    kwargs = {**_PRODUCTION_KWARGS, "redis_url": "redis://redis.example.com:6379/0"}
    with pytest.raises(ValidationError, match="redis_url"):
        Settings(**kwargs)  # type: ignore[arg-type]


def test_dev_mode_allows_plain_redis_url() -> None:
    """Settings(mode="dev") (the default) keeps the local redis:// URL default."""
    assert Settings().redis_url.startswith("redis://")


def test_unrelated_env_vars_are_not_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """extra="forbid" only rejects a value passed for a key that maps to no declared field.

    pydantic-settings' environment source only ever reads env vars matching a
    field's own name/validation_alias -- it never scans the rest of the process
    environment -- so an arbitrary, unrelated env var (or a typo of a real one,
    e.g. OIDC_AUDIANCE instead of OIDC_AUDIENCE) is simply absent from what the
    environment source hands to Settings, "forbid" or "ignore" alike.
    """
    monkeypatch.setenv("SOME_UNRELATED_ENV_VAR", "anything")
    monkeypatch.setenv("OIDC_AUDIANCE", "api")
    Settings()


def test_unrecognized_constructor_keyword_is_rejected() -> None:
    """extra="forbid" rejects an unrecognized key passed directly to the constructor."""
    with pytest.raises(ValidationError, match="extra_forbidden"):
        Settings(this_field_does_not_exist="x")  # type: ignore[call-arg]


def test_dev_mode_does_not_require_oidc_audience(monkeypatch: pytest.MonkeyPatch) -> None:
    """Settings(mode="dev") (the default) constructs fine with no oidc_audience set."""
    monkeypatch.delenv("OIDC_AUDIENCE", raising=False)
    assert Settings(mode="dev").oidc_audience is None


def test_mock_mode_requires_allow_mock_mode_flag() -> None:
    """Settings(mode="mock") with no allow_mock_mode raises ValidationError."""
    with pytest.raises(ValidationError, match="ALLOW_MOCK_MODE"):
        Settings(mode="mock")


def test_mock_mode_with_allow_mock_mode_succeeds() -> None:
    """Settings(mode="mock", allow_mock_mode=True) constructs without error."""
    settings = Settings(mode="mock", allow_mock_mode=True)
    assert settings.mode == "mock"
