"""Provider-agnostic OIDC bearer-token validation (Authorization Code + PKCE).

Only the OpenAPI-facing piece (the OAuth2AuthorizationCodeBearer scheme, used
to render the Swagger UI login flow) is built eagerly, from static settings.
Everything that needs the network -- fetching the provider's OIDC discovery
document and JWKS -- is deferred behind an lru_cache-wrapped function, so
importing this module (and therefore app.main, and therefore every unit test
using TestClient) never requires a running OIDC provider.

Also require_roles, a Keycloak-shaped RBAC dependency (reads the
resource_access.<client>.roles claim Keycloak's client-role mapper populates --
see app.crud_1.heroes/audit for routes that use it, and
app.controllers.mock for how MODE=mock issues tokens carrying that same shape).
"""

import logging
from collections.abc import Awaitable, Callable
from functools import lru_cache
from typing import Annotated, Any

import httpx
import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2AuthorizationCodeBearer
from jwt import PyJWKClient

from app.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

oauth2_scheme = OAuth2AuthorizationCodeBearer(
    authorizationUrl=settings.oidc_authorization_url,
    tokenUrl=settings.oidc_token_url,
)


@lru_cache
def _get_jwks_client() -> PyJWKClient:
    """Discover the provider's JWKS endpoint and return a caching client for it.

    A discovery-document fetch failure (provider outage, or a document missing
    `jwks_uri`) is reported as a 503 rather than left to propagate as an
    unhandled 500 -- get_current_claims logs every HTTPException it sees
    (see its own docstring), so this still lands in the same security log as a
    rejected token instead of silently bypassing it. `lru_cache` doesn't cache
    a raised exception, so a transient outage doesn't wedge this permanently.
    """
    discovery_url = f"{settings.oidc_issuer_url.rstrip('/')}/.well-known/openid-configuration"
    try:
        response = httpx.get(discovery_url, timeout=10)
        response.raise_for_status()
        jwks_uri: str = response.json()["jwks_uri"]
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service unavailable",
        ) from exc
    return PyJWKClient(jwks_uri, cache_keys=True)


def decode_bearer_token(token: str) -> dict[str, Any]:
    """Verify a bearer token's signature and standard claims, and return its payload.

    MODE=mock skips JWKS/network entirely and trusts whatever claims the token
    carries (see app.controllers.mock's POST /mock/token) -- a mock/test-only path,
    never used when MODE is dev or production. `# pragma: no cover` below is for
    tests/e2e specifically: it drives one live MODE=dev process, which can never
    take this branch -- tests/unit/test_oidc.py exercises it directly and still
    counts toward its own 95% gate.
    """
    try:
        if settings.mode == "mock":  # pragma: no cover
            return jwt.decode(token, options={"verify_signature": False})
        signing_key = _get_jwks_client().get_signing_key_from_jwt(token)
        return jwt.decode(
            token,
            signing_key.key,
            algorithms=[settings.oidc_algorithm],
            audience=settings.oidc_audience,
            issuer=settings.oidc_issuer_url,
            options={"verify_aud": settings.oidc_audience is not None},
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


async def get_current_claims(
    request: Request, token: Annotated[str, Depends(oauth2_scheme)]
) -> dict[str, Any]:
    """FastAPI dependency: validate the request's bearer token and return its claims.

    Logs a WARNING (path and status only -- there's no verified subject to include,
    since the token itself failed to validate) on every rejection, so brute-force/
    enumeration attempts against protected routes are detectable, and an IdP-outage
    503 from _get_jwks_client is visible here too rather than only in the 500 path
    (see app.problem_details for the matching unhandled-exception log).
    """
    try:
        return decode_bearer_token(token)
    except HTTPException as exc:
        logger.warning(
            "Rejected bearer token for %s (status=%d)", request.url.path, exc.status_code
        )
        raise


def require_roles(*roles: str) -> Callable[..., Awaitable[dict[str, Any]]]:
    """Build a dependency requiring at least one of the given Keycloak client roles.

    Reads claims["resource_access"][oidc_client_id]["roles"] -- the client-role claim
    shape Keycloak's default "roles" client scope populates (see realm-export.json),
    not a claim assumed to exist on every provider's tokens (see app/README.md).
    """

    async def _dependency(
        request: Request,
        claims: Annotated[dict[str, Any], Depends(get_current_claims)],
    ) -> dict[str, Any]:
        granted = set(
            claims.get("resource_access", {}).get(settings.oidc_client_id, {}).get("roles", [])
        )
        if not granted.intersection(roles):
            logger.warning(
                "Denied role check for %s: subject=%r has none of %r",
                request.url.path,
                claims.get("sub", "unknown"),
                roles,
            )
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient role")
        # Stashed on request.state so app.controllers.crud_actions's audit log can
        # name the caller without every route needing to redeclare this dependency
        # as a captured parameter just to get its return value.
        request.state.claims = claims
        return claims

    return _dependency
