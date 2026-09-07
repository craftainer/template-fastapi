# app/

The FastAPI application package (`app.main:app`), laid out as an MVC-ish
split across subpackages, each with its own `README.md`:

- `models/` — the Model layer: SQLAlchemy ORM.
- `views/` — the View layer: Pydantic schemas.
- `controllers/` — the Controller layer: the generic CRUD router
  factories, plus FastAPI routers with no resource of their own
  (health/auth/audit/mock).
- `crud_1/` — one subpackage per resource (e.g. `heroes/`), each
  combining its versioned sibling routers (built from `controllers/`'s
  factories) into one router, all combined into the single router
  `main.py` mounts at `/crud/v{ROUTER_VERSION}`; see its own `README.md`.
- `repositories/` — storage-agnostic CRUD access, backing `interfaces/`.
- `interfaces/` — the generic CRUD interface built from a view + a
  repository.
- `health/` — the health check interface and registry.

`config.py`/`main.py`/`oidc.py`/`telemetry.py`/`problem_details.py`/
`rate_limit.py`/`http_headers.py`/`xml_codec.py`/`web_components.py`/
`maintenance.py` stay flat, outside any subpackage — a flat module has no
resource-specific code and no state of its own beyond what it's explicitly
passed or reads from `app.config`.

- `config.py` — settings, read from environment variables; see
  "Configuration" and "MODE" below.
- `main.py` — FastAPI app instance, router wiring, and the lifespan hook
  that applies pending Alembic migrations on startup; see "Alembic
  migrations" below.
- `oidc.py` — provider-agnostic OIDC bearer-token validation (PKCE-
  compatible; not Keycloak-specific); see "OIDC / auth" below.
- `telemetry.py` — structured JSON logging setup; see "Structured
  logging / OTEL" below.
- `problem_details.py` — RFC 9457 error responses; see below.
- `rate_limit.py` — the Redis-backed `slowapi` limiter applied to
  `POST /mock/token` and each resource's bulk update/delete routes; see
  "Rate limiting" below.
- `http_headers.py` — the `Sunset`/`Deprecation` header dependency and
  the baseline security-headers middleware; see "Sunset/Deprecation
  headers" below.
- `xml_codec.py` / `web_components.py` — the generic XML and HTML-form
  rendering pieces a resource's sibling routers reuse; see
  `controllers/README.md`'s "Generic CRUD router factories" section for
  the pattern.
- `maintenance.py` — `purge_archived`, the out-of-request-path job that
  hard-deletes rows past `Settings.archive_purge_after_days` for every
  model carrying `app.models.mixins.Archivable`; invoked externally
  (`python -m app.maintenance`) by a host/k8s `CronJob`, never from
  `main.py` — see "Example CRUD resource: Hero" below and its own module
  docstring.

## Layering

Import order between all of the above is strict and one-directional —
lower layers never import from higher ones (`config` → `rate_limit` →
`telemetry` → `problem_details` → `oidc` → `models` → `maintenance` →
`views` → `repositories` → `interfaces` → `health` → `web_components` →
`xml_codec` → `http_headers` → `controllers` → `crud_1` → `main`) —
enforced by `import-linter`'s `layers` contract in `../../pyproject.toml`'s
`[tool.importlinter]`, run via `uv run lint-imports` (wired into
`../../.pre-commit-config.yaml`'s manual/pre-push stage, same as mypy).
A new subpackage or flat module gets added to that `layers` list at the
point matching its real dependencies, not appended blindly to one end --
`maintenance` sits directly above `models` (the only layer it imports from,
besides `config`/`oidc`/`problem_details`/`telemetry`/`rate_limit` below
that) since nothing else in `app/` imports it back (it's invoked externally,
`python -m app.maintenance`, never from `main.py`).
`crud_1` sits between `controllers` and `main` specifically because a
resource package imports `controllers.crud_router`'s factories to build
its own routers, and `main` imports the finished combined router from
`crud_1` rather than reaching into `controllers` for it. `interfaces`
now imports `aiomqtt` directly (`MQTTEventSink`/`MQTTEventSource`, see
"Example CRUD resource: Hero" below) — a third-party dependency, not
another `app/` module, so it doesn't change this layer order itself.

```mermaid
graph LR
    config --> rate_limit --> telemetry --> problem_details --> oidc
    oidc --> models --> maintenance --> views --> repositories --> interfaces
    interfaces --> health --> web_components --> xml_codec --> http_headers
    http_headers --> controllers --> crud_1 --> main
```

An arrow means "may import from" — each module may depend on anything
to its left, never anything to its right.

## Configuration

No application `.env` file: `config.py` reads settings from the process
environment only, which the compose files populate — see
`../../.devcontainer/stack/README.md`'s "Configuration" section for
where those values come from. `config.py` assembles any composed
connection string (`DATABASE_URL`) or renames a raw value to its own
generic field (`s3_access_key` from `RUSTFS_ACCESS_KEY`) at runtime,
since Compose can't interpolate a value from one env file into another
compose file's own env var. Values that are already a full, opaque,
provider-shaped string (the `OIDC_*` URLs) are written that way directly
in the owning service's env file instead, so `config.py` never has to
know a specific provider's URL scheme. Fixed in-network hostnames/ports
are not credentials and stay as plain literals in the consuming compose
file (e.g. `api`'s `POSTGRES_HOST: postgres`), not in an env file.

## Alembic migrations

Pending migrations apply automatically: `main.py`'s FastAPI `lifespan`
runs `alembic upgrade head` (off the event loop, via `asyncio.to_thread`
— Alembic's async recipe in `../../alembic/env.py` runs its own
`asyncio.run` internally, which can't nest inside one already running)
before the app starts serving. That only fires for a real ASGI startup
(`uvicorn`, the `runner` image, `tests/e2e`) — a bare `TestClient(app)`
in `tests/unit`/`tests/integration` never triggers lifespan, so those
suites need the schema already migrated; the devcontainer's own
`postCreateCommand` runs `uv run alembic upgrade head` once up front for
exactly that reason. `../../alembic.ini`/`../../alembic/` are resolved
relative to the current working directory (plain
`Config("alembic.ini")`), which is the repo root under the
devcontainer/pytest and `/app` in the `runner` image (see the
Dockerfile's `runner` stage, which `COPY`s both there) — never hardcode
a different path. See `../../alembic/README.md` for how migrations
themselves are authored.

`../../scripts/runner.sh` stays a plain entrypoint — migrations run from
Python, in `main.py`'s lifespan, never from the shell script.

## OIDC / auth

`../../.devcontainer/stack/keycloak/` runs Keycloak with dev-mode realm
auto-import; see its own `README.md` for the realm/client/test-user
details. `oidc.py` validates bearer tokens against it via generic OIDC
discovery + JWKS (`PyJWKClient`), with no Keycloak-specific code — any
Authorization Code + PKCE provider works by pointing
`OIDC_ISSUER_URL`/`OIDC_AUTHORIZATION_URL`/`OIDC_TOKEN_URL` elsewhere.
Add auth to a route with `Depends(get_current_claims)`; routes that
don't take that dependency stay public.

`oidc_audience` (`OIDC_AUDIENCE`) is required — `config.py`'s validation
refuses to construct `Settings` with `MODE=production` and no
`oidc_audience` set — because `decode_bearer_token` only verifies the
JWT's `aud` claim when it's set, and an unchecked audience would accept
a token issued for any other client of the same provider. `dev`/`mock`
stay opt-in (`../../.devcontainer/stack/keycloak/keycloak.env` sets it
anyway, via the `api` client's `api-audience` protocol mapper in
`realm-export.json`, so every mode's tokens actually carry it).
`config.py`'s validation similarly refuses `MODE=production` with
`oidc_issuer_url` left at `http://` (the JWKS/discovery fetch, and the
Authorization Code token exchange, would otherwise happen in cleartext),
or with `postgres_password`/`s3_access_key`/`s3_secret_key` left at their
local/devcontainer default values.

`oidc.py` logs a `WARNING` (with the request path) on every rejected
bearer token, and `require_roles` logs one (path + subject + the roles
that were required) on every `403` — both to make brute-force/enumeration
attempts against protected routes detectable (see `telemetry.py`'s
"Structured logging / OTEL" below for where that log line ends up).

### RBAC

Each Keycloak test user carries one client role on the `api` client
matching that user's name (`viewer`/`editor`/`maintainer`/`security`/
`detective` — see `../../.devcontainer/stack/keycloak/README.md`).
`oidc.py`'s `require_roles(*roles)` builds a dependency reading
`claims["resource_access"][oidc_client_id]["roles"]` — Keycloak's
client-role claim shape specifically, not something assumed present on
every provider's token (unlike `get_current_claims`, which stays
provider-agnostic). Add a role requirement to a route with
`dependencies=[Depends(require_roles("editor", "maintainer"))]` — see
`controllers/README.md` for the reusable-constant pattern. A new
resource's routes pick their own role names/mapping; there's no fixed
role list beyond what `realm-export.json` defines.

## MODE (dev / mock / production)

`config.py`'s `Settings.mode` (env var `MODE`) is `"dev"`, `"mock"`, or
`"production"`, read once at import time everywhere it's used (the same
pattern as `get_settings()` generally) — it's a startup-time setting,
not a per-request one.

- `dev` (the default): `main.py` starts `debugpy` listening on
  `127.0.0.1:5678` for a remote attach (non-blocking — never
  `wait_for_client()` — and loopback-only, since the devcontainer's own
  port forwarding reaches it there without needing every interface) and
  sets FastAPI's `debug=True`. `../../.devcontainer/compose.yml` sets
  `MODE: dev`.
- `mock`: every external service is replaced with a local fake, so the
  app needs zero containers to boot — `repositories.memory.
  InMemoryRepository` instead of `SQLAlchemyRepository` (Alembic
  migrations are skipped entirely), `health.checks.MockHealthCheck`
  instead of the real per-service checks, and `oidc.
  decode_bearer_token` skips JWKS/network and trusts the token's claims
  as-is. `POST /mock/token` (`controllers.mock`, mounted only in this
  mode) issues a token shaped like a real Keycloak one (same
  `resource_access.<client>.roles` claim), so RBAC is exercisable
  without Keycloak too. Because it bypasses auth entirely, `MODE=mock`
  also requires `ALLOW_MOCK_MODE=1` (`Settings.allow_mock_mode`) —
  `config.py`'s validation refuses to construct `Settings` with
  `MODE=mock` and no `ALLOW_MOCK_MODE`, so the mode can never be reached
  by `MODE`'s own default/typo alone. `tests/e2e/conftest.py` sets it for
  its own `MODE=mock` parametrized leg; a future local-only use beyond
  that adds it explicitly alongside `MODE=mock`.
- `production`: no debugger. The `../../Dockerfile`'s `runner` stage
  sets `ENV MODE=production` as the single source of truth for that
  default.

A resource that wants `MODE=mock` support builds its CRUD dependency from
`app.interfaces.dependency.build_repository_provider(Model)` the way
`crud_1.heroes.heroes_v2.get_hero_crud` does — keep the dependency's signature
identical across modes (an unused `AsyncSession`'s `commit()` never opens
a connection, so taking `app.models.base.DBSession` unconditionally and letting
`build_repository_provider` branch on `settings.mode` internally is both
simpler and satisfies mypy's identical-conditional-signature check, versus
two differently-signatured functions).

## Structured logging / OTEL

`telemetry.py`'s `configure_logging()` (called once from `main.py`, at
import time) attaches a JSON-formatting handler to the root logger
unconditionally — every log call (including uvicorn's own) prints one
structured JSON line to stdout. If `OTEL_EXPORTER_OTLP_ENDPOINT` is set,
it additionally bridges the root logger to an OTLP log exporter. Logs
only, deliberately — no tracing/metrics instrumentation. OTEL's own env
vars (endpoint, headers, protocol, compression, certificate) are read
directly by `OTLPLogExporter()` itself, never re-modeled as `Settings`
fields — OTEL's env-var convention is already the single source of
truth for those.

Every non-reserved `LogRecord` attribute (i.e. anything passed via a call's
own `extra={...}`) is redacted to `"[REDACTED]"` before being serialized if
its key looks credential-shaped (`token`, `password`, `secret`,
`authorization`, `claims`, `credential`, matched as a case-insensitive
substring) — a denylist, not an allowlist, so a future `logger.info(...,
extra={"access_token": ...})` can't leak it into stdout/OTLP verbatim.

## RFC 9457 error responses

`problem_details.py`'s `register_problem_handlers(app)` (called once
from `main.py`) turns every `HTTPException` (raised anywhere, e.g.
`crud_1/heroes/heroes_v2.py`'s `raise HTTPException(status.
HTTP_404_NOT_FOUND, ...)`, unchanged), FastAPI's request validation
errors, and any other unhandled exception into a single consistent
`application/problem+json` body — no route needs to build this itself.
A route that wants a specific `detail` message just raises
`HTTPException` normally. Every otherwise-unhandled exception is also
logged (`logger.exception`, with the request path) before being turned
into the generic 500 body, so a genuine bug or attack attempt leaves a
server-side trace instead of vanishing into a bare response.

## Sunset/Deprecation headers

`http_headers.py`'s `sunset(at, link=...)` is a reusable dependency
(`Depends(sunset(...))`) that sets RFC 8594's `Sunset` header (an
HTTP-date, not ISO 8601/IXDTF) plus a `Deprecation` header on a route —
see `controllers/protected.py` for the applied example. See
`views/README.md`'s `IXDTFDatetime` for how read views serialize their
own timestamps.

`http_headers.py`'s `add_security_headers(app)` is unconditional
middleware (`main.py` calls it once, right after
`register_problem_handlers`) that sets `Content-Security-Policy`,
`X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`,
`Strict-Transport-Security`, `Referrer-Policy`, and `Permissions-Policy`
on every response, including ones a route's own dependencies never run
for (a 404, an RFC 9457 error body) — unlike `sunset()` above, no route
opts into this individually. `/docs`/`/redoc` get a separately relaxed
`Content-Security-Policy` (Swagger UI/Redoc's own CDN script/style
tags), applied by the same middleware based on request path.

## Rate limiting

`rate_limit.py`'s `limiter` (a `slowapi.Limiter`, backed by this app's
Redis service — `Settings.redis_url`, shared across worker processes)
is applied per-route via `@limiter.limit(...)`, not as global
middleware: `app.controllers.mock`'s `POST /mock/token`
(`Settings.rate_limit_mock_token`, default `10/minute`) and every
resource's generated bulk update/delete routes
(`Settings.rate_limit_bulk_action`, default `20/minute`, exempted for a
single-record `?id=` request via `exempt_single_record_action`) — see
`rate_limit.py`'s own module docstring for why this stays per-route
instead of `slowapi.middleware.SlowAPIMiddleware` (a
`BaseHTTPMiddleware`, which `_SecurityHeadersMiddleware`'s own docstring
above documents as unsafe for this app). `slowapi.errors.
RateLimitExceeded` is itself an `HTTPException` subclass (`429`), so
`problem_details.py`'s existing handler renders it as a normal RFC 9457
body with no separate wiring. `tests/e2e/conftest.py` raises both limits
generously for its own live process, since one e2e run's cumulative
login/bulk-action traffic would otherwise trip the production defaults
itself — `tests/unit/test_rate_limit.py` verifies the actual enforcement
against a throwaway `Limiter` instead.

## Example CRUD resource: Hero

`models/hero.py` / `views/hero_v2.py` / `crud_1/heroes/heroes_v2.py` are a
worked example of the generic CRUD interface, wired up as
`/crud/v1/heroes/v2/json` (list/create/get/update/delete — see
`crud_1/heroes/heroes_v2.py`; `/xml` and `/web` siblings also exist, see
`controllers/README.md`'s "Generic CRUD router factories"). Adding
another resource follows the same three-file shape: an `IdentifiedBase`
subclass in `models/`, an `ORMView` subclass (plus `*Create`/`*Update`
variants) in `views/`, and a router in `controllers/` that builds a
`CRUDInterface(schema=<View>, repository=SQLAlchemyRepository(session,
<Model>))` per request — see `interfaces/README.md` and
`repositories/README.md` for what each side of that call does.

```mermaid
sequenceDiagram
    participant Client
    participant Controller as crud_1/heroes/heroes_v2.py
    participant CRUD as interfaces/base.py (CRUDInterface)
    participant Repo as repositories/sqlalchemy.py
    participant DB as Postgres

    Client->>Controller: GET /crud/v1/heroes/v2/json?id={id}
    Controller->>CRUD: get(id)
    CRUD->>Repo: get(id)
    Repo->>DB: SELECT ... WHERE id = ?
    DB-->>Repo: row
    Repo-->>CRUD: ORM model
    CRUD-->>Controller: View (from_attributes)
    Controller-->>Client: 200 JSON
```

Under `MODE=mock`, `Repo`/`DB` are replaced by
`repositories/memory.py`'s `InMemoryRepository`, with no other layer
changing — see "MODE (dev / mock / production)" above.

`/crud/v1/heroes/v2/json` also supports schema-driven filtering/sorting
(e.g. `?name__icontains=man&sort=-created_at`) and bulk update/delete
over a filter set (`PATCH`/`DELETE` with no `id`) — see
`controllers/README.md`'s "Generic CRUD router factories" and
`docs/adrs/0008-generic-schema-driven-query-and-bulk-actions.md` for why
that logic lives in the shared repository/CRUD layers rather than in
`heroes.py` itself.

Hero also carries a deprecated `/crud/v1/heroes/v1` sibling version,
backed by the same data — see `controllers/README.md`'s "API and model
versioning" and `docs/adrs/0009-explicit-crud-router-and-model-
versioning-segments.md` for the path-segment versioning convention any
future breaking resource change follows.

Hero is also the worked example of `interfaces/base.py`'s opt-in
`OwnerScope` hook: `get_hero_crud` passes `OwnerScope("owner_id",
claims["sub"], read_scoped=False)`, so every authenticated caller still
reads every hero (`read_scoped=False` keeps list/get shared, same as
before this was added), but `update`/`delete` — single or bulk — only
ever reach heroes the caller themselves created. See
`docs/adrs/0011-owner-scoped-crud-example-resource.md` for why this
shape was chosen and `interfaces/README.md`'s `OwnerScope` paragraph for
the mechanism a new per-user/per-tenant resource opts into the same way.

### Record-lifecycle mixins

Hero also demonstrates every opt-in record-lifecycle mixin from
`models/mixins.py`, on `/crud/v1/heroes/v2` only (not the deprecated `v1`
sibling, matching how bulk actions were rolled out as a v2-only
capability) — across all three of its `/json`, `/xml`, and `/web`
sibling routers, not JSON-only (see `controllers/README.md`'s "Generic
CRUD router factories" for the XML hand-assembled-nesting/web
generated-JS shape each takes):

- **Archive** (`Archivable`): `DELETE` sets `archived_at` instead of
  removing the row; excluded from `GET` by default, included with
  `?include_archived=true`. `POST /restore?id=` (or with filters, in
  bulk) clears it — same id-or-filters/single-or-bulk shape as delete.
- **Draft** (`Draftable`): `POST /draft` accepts `HeroV2Update`'s
  all-optional shape and persists with `is_draft=True`. `POST
  /publish?id=` re-validates the record against `HeroV2Create` (422,
  naming missing fields, if it still doesn't validate) and flips
  `is_draft=False`. A plain `GET` includes drafts by default — see
  `models/mixins.py`'s `Draftable` docstring for why this default is
  provisional, pending a real (non-Hero) draftable resource.
- **Scheduled publish/unpublish** (`Schedulable`): `publish_at`/
  `unpublish_at` are plain columns, set via a normal `PATCH`; a record
  outside that window is excluded from `GET` by default, included with
  `?include_unpublished=true`. No background job involved — visibility
  is computed from `datetime.now(UTC)` at query time.
- **Scheduled purge**: `app.maintenance.purge_archived`, external to the
  app's own request path — see `app.maintenance`'s own module docstring
  and `Settings.archive_purge_after_days`.
- **Duplicate/clone**: `POST /clone?id=` — generic, no mixin needed;
  every resource gets it once it uses `build_json_router`.
- **Lock/read-only** (`Lockable`): `is_locked` is a plain field, set via
  a normal `PATCH`; while `True`, `app.repositories`' `update`/`delete`
  (single or bulk) raise `RecordLockedError`, surfaced as `423 Locked` —
  except a `PATCH` whose own body sets `is_locked=false`, which is
  always allowed through (so unlocking never needs a dedicated route,
  but can also edit other fields in the same request).
- **Revision history**: `get_hero_crud` passes
  `revisions=RepositoryRevisionSink(...)`/`resource="hero"`/`actor=...`
  to `CRUDInterface`; every create/update/update_many/delete/delete_many
  is logged to the shared `revisions` table (`app.models.revision.
  Revision`). `GET /revisions?id=` returns a record's history, newest
  first.
- **Real-time event stream**: `get_hero_crud` passes
  `events=build_event_sink_provider("hero")(...)` to `CRUDInterface`;
  every create/update/update_many/delete/delete_many **and**
  restore/restore_many publishes an event. `GET /events` (added via
  `event_source_dependency=`) streams them back over Server-Sent Events,
  backed by MQTT (`.devcontainer/stack/mqtt/`) in dev/production or an
  in-memory fan-out under `MODE=mock` — see `interfaces/README.md`'s
  `EventSink`/`EventSource` paragraph and
  `docs/adrs/0015-mqtt-for-crud-events.md` for the delivery-guarantee
  design (a subscriber that preserves its `subscriber_id` doesn't miss
  events across a brief disconnect).
- **Statistics/predictions**: `stats_enabled=True` adds `GET /stats`
  (count, per-numeric-field min/max/avg/sum, per-categorical-field (bool/
  enum) value distribution, an optional `?bucket=day|week|month`
  time-bucketed count series over `created_at`, and Hero's own lifecycle
  breakdown from every mixin above) and `GET /predict` (a naive
  ordinary-least-squares linear-regression forecast over that same
  time-bucketed series, `?periods=` future buckets, `?field=` to target a
  numeric field's per-bucket sum instead of record count — always named
  `"linear_regression"` in the response, never mistaken for a trained
  model). See `controllers/README.md`'s "Generic CRUD router factories"
  for the full shape, `repositories/README.md`'s "Statistics" section for
  what the repository layer computes, and
  `docs/plans/2026-09-crud-stats-and-predictions.md` for the design.

## Do

- Add new settings as typed fields on `Settings` in `config.py`, sourced
  from the compose files' `environment:` blocks.
- Annotate every function signature — `mypy --strict` and ruff's `ANN`
  rules both require it.
- Add auth to a new route with `Depends(get_current_claims)` from
  `oidc.py` — a route with no such dependency is public.
- Register a new external service's health check with
  `HealthRegistry.register` in `health/registry.py`'s
  `get_health_registry` — see `health/README.md`.

## Don't

- Read from a `.env` file, or add one back — see `docs/TEMPLATE.md`'s
  "Don't" section.
- Hardcode a real secret's value here — real secrets belong in
  `.secrets/`, referenced from a compose file.
- Assume a claim beyond `sub` is present on every provider's tokens —
  `decode_bearer_token`'s return value is whatever the provider's JWT
  contains, and that shape isn't guaranteed across providers.
- Import "up" the layering described above (e.g. `models/` importing
  from `controllers/`) — `uv run lint-imports` fails the build on it.
