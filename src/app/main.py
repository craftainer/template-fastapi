"""FastAPI app entrypoint: wires up settings, migrations, routers, and lifespan."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

import debugpy
from alembic.config import Config
from fastapi import FastAPI

from alembic import command
from app.config import get_settings
from app.controllers import (
    audit,
    health,
    mock,
)
from app.crud_1 import router as crud_v1_router
from app.http_headers import add_security_headers
from app.problem_details import register_problem_handlers
from app.telemetry import configure_logging
from crud.controllers.crud_router import ROUTER_VERSION

settings = get_settings()
configure_logging()


def _run_migrations() -> None:
    """Apply any pending Alembic migrations against the configured database.

    Blocking (Alembic's async recipe runs its own asyncio.run internally), so the
    caller must run this off the event loop -- see lifespan below. `alembic.ini` is
    resolved relative to the current working directory: the repo root in the
    devcontainer and under pytest, /app in the runner image (see the root
    Dockerfile's runner stage, which copies alembic.ini/alembic/ there).
    """
    command.upgrade(Config("alembic.ini"), "head")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Apply pending migrations before serving, then run normally until shutdown.

    MODE=mock skips migrations entirely -- there's no database to migrate against
    (see crud.repositories.memory). `# pragma: no branch` below is for tests/e2e
    specifically: its one live process is always MODE=dev, so the other branch can
    never run there -- tests/unit/test_main.py exercises it directly and still
    counts toward its own 95% gate.
    """
    if settings.mode != "mock":  # pragma: no branch
        await asyncio.to_thread(_run_migrations)
    yield


def _enable_debugger() -> None:
    """Start listening for a remote debugger attach on :5678 (MODE=dev only).

    Doesn't call wait_for_client(): startup must not block when nobody attaches.
    When the process is already launched under VS Code's own debugpy (the
    "FastAPI: api" launch config in .vscode/launch.json), debugpy is already
    injected and a second listen() raises RuntimeError -- expected, not an error,
    so it's swallowed here.
    """
    with suppress(RuntimeError):
        # 127.0.0.1, not 0.0.0.0: VS Code's remote-attach reaches this through the
        # devcontainer's own port forwarding (see .devcontainer/compose.yml), which
        # connects to the container's loopback interface -- binding every interface
        # would also accept a debugger connection from elsewhere on the container's
        # network, with no ALLOW_MOCK_MODE-style second gate the way MODE=mock has.
        debugpy.listen(("127.0.0.1", 5678))


def _configure_debugger(mode: str) -> None:
    """Enable the remote debugger when the given mode is "dev".

    `# pragma: no branch` below is for tests/e2e specifically: its one live
    process is always MODE=dev, so the other branch can never run there --
    tests/unit/test_main.py exercises it directly and still counts toward its
    own 95% gate.
    """
    if mode == "dev":  # pragma: no branch
        _enable_debugger()


def _mount_mode_specific_routers(app: FastAPI, mode: str) -> None:
    """Mount routers that only make sense for the given mode.

    Currently just POST /mock/token (app.controllers.mock) for MODE=mock -- see
    app.controllers.mock's docstring for why it's mode-gated. The mock branch is
    `# pragma: no cover` for tests/e2e specifically: its one live process is
    always MODE=dev, so this branch can never run there -- tests/unit/test_main.py
    exercises it directly and still counts toward its own 95% gate.
    """
    if mode == "mock":  # pragma: no cover
        app.include_router(mock.router, prefix="/mock")


_configure_debugger(settings.mode)

app = FastAPI(
    title=settings.app_name,
    lifespan=lifespan,
    debug=settings.mode == "dev",
    swagger_ui_init_oauth={
        "usePkceWithAuthorizationCodeGrant": True,
        "clientId": settings.oidc_client_id,
    },
)
register_problem_handlers(app)
add_security_headers(app)

app.include_router(health.router, prefix="/health")
app.include_router(crud_v1_router, prefix=f"/crud/v{ROUTER_VERSION}")
app.include_router(audit.router, prefix="/audit")
_mount_mode_specific_routers(app, settings.mode)
