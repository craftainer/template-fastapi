"""Redis-backed per-route rate limiting for this app's most abuse-prone routes.

Built on slowapi (https://github.com/laurentS/slowapi) over the `limits` library,
backed by this app's already-provisioned Redis service (`app.config.Settings.
redis_url`) so the counter is shared across every worker process, not per-process.

Deliberately per-route (`limiter.limit(...)` applied to POST /mock/token and each
resource's bulk update/delete routes -- its highest-risk, unauthenticated-or-
destructive surface, per the OWASP hardening pass this was added in), not global
`SlowAPIMiddleware`: that middleware is a `starlette.middleware.base.
BaseHTTPMiddleware`, which app.http_headers's own `_SecurityHeadersMiddleware`
docstring documents as breaking a regression test by splitting a single
"http.response.body" ASGI message into more than one. `limiter.limit(...)` needs no
middleware -- it checks the limit inline in the route's own call, before the
handler body runs.

Applied to a route's update/delete/restore handler as a whole (see
crud.controllers.crud_router), not just its bulk branch -- a single-record
edit (`?id=`) shares the same budget as a bulk one, since exempting single-
record calls would leave per-record updates/deletes unrated regardless of
how many a single client issues.

`slowapi.errors.RateLimitExceeded` is itself a `starlette.exceptions.HTTPException`
subclass (status_code=429), so app.problem_details's existing StarletteHTTPException
handler already renders it as a normal RFC 9457 problem-details body -- no separate
exception handler needed here.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

from app.config import get_settings

settings = get_settings()

limiter = Limiter(key_func=get_remote_address, storage_uri=settings.redis_url)
