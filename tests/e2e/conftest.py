"""E2E fixture overrides: point Playwright at the running api container,
and at a browser served by the selenium container instead of a local one.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from collections.abc import Callable, Generator
from pathlib import Path
from urllib.parse import urlparse

import httpx
import pytest
from playwright.sync_api import Browser, Playwright
from selenium.webdriver import ChromeOptions, Remote

from app.config import get_settings

_STARTUP_TIMEOUT_SECONDS = 10.0

# Each parametrized mode gets its own port so both legs' api processes can run
# for the same pytest session without colliding.
_MODE_PORTS = {"dev": 8000, "mock": 8001}

_REALM_EXPORT_PATH = (
    Path(__file__).resolve().parents[2] / ".devcontainer/stack/keycloak/realm-export.json"
)

# The api subprocess below runs the same app code the coverage gate measures
# for tests/unit and tests/integration; give it the same coverage config and
# a sitecustomize.py (via PYTHONPATH) so it starts measuring itself on launch
# and pytest-cov can combine its data with this process's at session end --
# see sitecustomize.py and pyproject.toml's [tool.coverage.run].
_COVERAGE_SUBPROCESS_ENV = {
    "COVERAGE_PROCESS_START": str(Path(__file__).resolve().parents[2] / "pyproject.toml"),
    "PYTHONPATH": os.pathsep.join(
        [
            str(Path(__file__).resolve().parent),
            *([os.environ["PYTHONPATH"]] if "PYTHONPATH" in os.environ else []),
        ]
    ),
}


@pytest.fixture(scope="session", params=["dev", "mock"])
def app_mode(request: pytest.FixtureRequest) -> str:
    """Which MODE the app-under-test boots under for this parametrized leg."""
    return request.param  # type: ignore[no-any-return]


@pytest.fixture(scope="session")
def base_url(app_mode: str) -> str:
    """Return this mode's api base URL, overridable via E2E_BASE_URL for the dev leg only.

    Mock's whole point is not depending on an externally-managed instance, so it
    always gets its own fixed port instead.
    """
    if app_mode == "dev" and "E2E_BASE_URL" in os.environ:
        return os.environ["E2E_BASE_URL"]
    return f"http://api:{_MODE_PORTS[app_mode]}"


@pytest.fixture(scope="session", autouse=True)
def _running_app(app_mode: str, base_url: str) -> Generator[None]:
    """Start the api server for the duration of the e2e run, unless one is
    already up (e.g. under the "FastAPI: api" launch config) or E2E_BASE_URL
    points somewhere this suite doesn't own (dev leg only).
    """
    if app_mode == "dev" and "E2E_BASE_URL" in os.environ:
        yield
        return

    health_url = f"{base_url}/health/live"
    try:
        httpx.get(health_url, timeout=1).raise_for_status()
        yield
        return
    except httpx.HTTPError:
        pass

    port = urlparse(base_url).port
    uvicorn = shutil.which("uvicorn")
    if uvicorn is None:
        raise RuntimeError("uvicorn not found on PATH")
    mode_env = {
        "MODE": app_mode,
        **({"ALLOW_MOCK_MODE": "1"} if app_mode == "mock" else {}),
        # Generous, not the small production defaults: every e2e test file's own
        # login/bulk-action calls share one real Redis-backed counter (keyed by
        # client address, not per test), and this suite's own traffic volume would
        # otherwise trip app.rate_limit's rate_limit_mock_token/rate_limit_bulk_action
        # defaults well before any test intends to exercise rate limiting itself --
        # that's covered directly instead, in tests/unit/test_rate_limit.py.
        "RATE_LIMIT_MOCK_TOKEN": "1000/minute",
        "RATE_LIMIT_BULK_ACTION": "1000/minute",
        # Short, not the 15s production default: test_hero_events_e2e.py waits for a
        # real keep-alive comment on an idle GET .../events subscription, and doing
        # that at the production interval would make that test needlessly slow.
        "SSE_KEEPALIVE_SECONDS": "0.2",
    }
    # 0.0.0.0: must be reachable from the sibling selenium container, not
    # just loopback -- same as the root README's manual startup command.
    # Fixed args plus our own parsed base_url's port, not external input.
    process = subprocess.Popen(  # noqa: S603
        [uvicorn, "app.main:app", "--host", "0.0.0.0", "--port", str(port)],  # noqa: S104
        env={**os.environ, **_COVERAGE_SUBPROCESS_ENV, **mode_env},
    )
    try:
        deadline = time.monotonic() + _STARTUP_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            try:
                httpx.get(health_url, timeout=1).raise_for_status()
                break
            except httpx.HTTPError:
                time.sleep(0.2)
        else:
            process.terminate()
            process.wait(timeout=5)
            raise RuntimeError(
                f"api server did not become healthy within {_STARTUP_TIMEOUT_SECONDS}s"
            )
        yield
    finally:
        process.terminate()
        process.wait(timeout=5)


@pytest.fixture(scope="session")
def browser(playwright: Playwright) -> Generator[Browser]:
    """Connect to the selenium container's Chromium over CDP.

    No browser binaries are installed in this container -- see
    tests/e2e/README.md for why the browser itself lives in a separate
    container that Playwright connects to remotely instead.
    """
    selenium_url = os.environ.get("E2E_SELENIUM_URL", "http://selenium:4444")
    driver = Remote(command_executor=f"{selenium_url}/wd/hub", options=ChromeOptions())
    try:
        cdp_url = str(driver.capabilities["se:cdp"])
        browser = playwright.chromium.connect_over_cdp(cdp_url)
        try:
            yield browser
        finally:
            browser.close()
    finally:
        driver.quit()


def _dev_realm_client_roles() -> dict[str, list[str]]:
    """Map each dev-realm username to its client roles on the "api" client.

    Read out of realm-export.json rather than hand-duplicated here, so the mock
    leg's role mapping can never drift from the real dev-realm one it stands in for.
    """
    realm = json.loads(_REALM_EXPORT_PATH.read_text())
    return {user["username"]: user["clientRoles"]["api"] for user in realm["users"]}


@pytest.fixture(scope="session")
def access_token(app_mode: str, base_url: str) -> Callable[[str], str]:
    """Return a function that logs in `username` and returns their access token.

    Under `dev`, a real password-grant login against the dev-realm Keycloak. Under
    `mock`, POST /mock/token with the same username's client roles from
    realm-export.json, so every test can call access_token("editor") unchanged
    regardless of mode.
    """
    if app_mode == "mock":
        client_roles = _dev_realm_client_roles()

        def _fetch_mock(username: str) -> str:
            response = httpx.post(
                f"{base_url}/mock/token",
                json={"sub": username, "roles": client_roles[username]},
                timeout=10,
            )
            response.raise_for_status()
            return response.json()["access_token"]  # type: ignore[no-any-return]

        return _fetch_mock

    settings = get_settings()

    def _fetch(username: str) -> str:
        """Log in `username` (dev-realm password == username) and return their access token."""
        response = httpx.post(
            settings.oidc_token_url,
            data={
                "grant_type": "password",
                "client_id": settings.oidc_client_id,
                "username": username,
                "password": username,
            },
            timeout=10,
        )
        response.raise_for_status()
        return response.json()["access_token"]  # type: ignore[no-any-return]

    return _fetch
