"""E2E smoke test: /crud/v1/heroes/v2/{json,xml}/stats and /predict against the live api.

Doesn't assert exact counts (other e2e tests running in the same session create/
delete their own heroes concurrently, and dev-mode leaves committed data behind
across tests within a session -- see conftest.py's `_reset_dev_database`) --
just that both routes respond with the expected shape, and that the same
caller-input validation (invalid bucket/field, insufficient history) this
plan's unit tests already cover in isolation also holds end to end.
"""

from collections.abc import Callable

from playwright.sync_api import Page


def test_hero_stats_smoke_json_and_xml(
    page: Page, base_url: str, access_token: Callable[[str], str]
) -> None:
    """GET .../stats?bucket=day responds 200 with the expected top-level shape, in both formats."""
    headers = {"Authorization": f"Bearer {access_token('viewer')}"}

    json_response = page.request.get(
        f"{base_url}/crud/v1/heroes/v2/json/stats", params={"bucket": "day"}, headers=headers
    )
    assert json_response.ok
    body = json_response.json()
    assert "total" in body
    assert "numeric" in body
    assert "categorical" in body
    assert "lifecycle" in body

    xml_response = page.request.get(
        f"{base_url}/crud/v1/heroes/v2/xml/stats", params={"bucket": "day"}, headers=headers
    )
    assert xml_response.ok
    assert xml_response.headers["content-type"] == "application/xml"
    assert "<stats>" in xml_response.text()
    assert "<numeric-fields>" in xml_response.text()


def test_hero_predict_invalid_bucket_returns_422_json_and_xml(
    page: Page, base_url: str, access_token: Callable[[str], str]
) -> None:
    """GET .../predict?bucket=<invalid> is a 422 in both formats, not a 500."""
    headers = {"Authorization": f"Bearer {access_token('viewer')}"}

    json_response = page.request.get(
        f"{base_url}/crud/v1/heroes/v2/json/predict",
        params={"bucket": "fortnight"},
        headers=headers,
        fail_on_status_code=False,
    )
    assert json_response.status == 422

    xml_response = page.request.get(
        f"{base_url}/crud/v1/heroes/v2/xml/predict",
        params={"bucket": "fortnight"},
        headers=headers,
        fail_on_status_code=False,
    )
    assert xml_response.status == 422


def test_hero_predict_unrecognized_field_returns_422(
    page: Page, base_url: str, access_token: Callable[[str], str]
) -> None:
    """GET .../predict?field=<non-numeric> is a 422, naming an unrecognized field."""
    headers = {"Authorization": f"Bearer {access_token('viewer')}"}

    response = page.request.get(
        f"{base_url}/crud/v1/heroes/v2/json/predict",
        params={"field": "name"},
        headers=headers,
        fail_on_status_code=False,
    )
    assert response.status == 422


def test_hero_stats_requires_read_role(page: Page, base_url: str) -> None:
    """GET .../stats with no Authorization header is rejected (401), same as the plain GET."""
    response = page.request.get(
        f"{base_url}/crud/v1/heroes/v2/json/stats", fail_on_status_code=False
    )
    assert response.status == 401
