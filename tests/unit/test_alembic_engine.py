"""Unit test: alembic/env.py connects with the app's own engine (TLS mode and timeouts)."""

from pathlib import Path

import pytest
from alembic.config import Config

from alembic import command
from app import db
from app.config import Settings, get_settings

_ROOT = Path(__file__).resolve().parents[2]


class _EngineBuilt(Exception):  # noqa: N818 -- a test sentinel, not an error condition
    """Raised by the stand-in `build_engine` so no database is needed."""


def test_online_migrations_build_their_engine_with_app_db_build_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The migration session gets `build_engine(get_settings())`: same ssl and timeouts."""
    seen: list[Settings] = []

    def _build_engine(settings: Settings) -> None:
        seen.append(settings)
        raise _EngineBuilt

    monkeypatch.setattr(db, "build_engine", _build_engine)
    config = Config(str(_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(_ROOT / "alembic"))
    with pytest.raises(_EngineBuilt):
        command.upgrade(config, "head")
    assert seen == [get_settings()]


def test_connect_args_carry_the_ssl_mode_and_timeouts() -> None:
    """`build_connect_args` is the one place TLS mode and timeouts are mapped for asyncpg."""
    settings = Settings(
        mode="dev", postgres_sslmode="verify-full", db_connect_timeout=3, db_command_timeout=7
    )
    assert db.build_connect_args(settings) == {
        "ssl": "verify-full",
        "timeout": 3,
        "command_timeout": 7,
    }
    assert db.build_connect_args(Settings(mode="dev")) == {}
