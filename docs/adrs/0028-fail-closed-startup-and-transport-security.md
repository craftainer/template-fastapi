# 0028. Fail closed at startup: required MODE, TLS to the broker and to Postgres for migrations

## Status

Accepted.

## Context

The OWASP review of this template (`.claude/ow-reports/OW-template-fastapi.md` in the
orchestrating workspace) and the library releases `craftainer-crud` 0.10 and
`craftainer-observability` 0.5 call for several secure-by-default changes that belong together:

- `MODE` defaulted to `dev`, and the runner image set `MODE=production` itself. A deployment
  outside the image that forgot `MODE` ran with the debugger, open `/docs` and exception text
  in 500 bodies (OWASP A02, secure configuration).
- `alembic/env.py` built its own engine with no `connect_args`, so the migration session
  ignored `POSTGRES_SSLMODE` and the connect and command timeouts that the request path
  honors (A04, ASVS 12.3.1).
- `craftainer-crud` 0.10 adds an MQTT TLS and credentials API, after-commit event delivery,
  per-caller stream limits, and an optional `scope_dependency` for `/events`. The dev broker
  was anonymous plaintext, so a dev setup could pass where production would fail.
- A signed token without `sub` reached `claims["sub"]` and surfaced as a 500.

## Decision

We will:

- Give `Settings.mode` **no default**. The app refuses to start without `MODE`
  (`dev`, `mock` or `production`; any other value is also an error). The runner image no longer
  sets `MODE`; every launcher sets it: `.devcontainer/compose.instance.yml` (`dev`), the smoke
  stack `compose.yml` (`production`), `image.mk`'s image runs (`mock`, `dev`) and the test
  suites.
- Build Alembic's engine with `app.db.build_engine(get_settings())`, so migrations use the
  same TLS mode and timeouts as requests. `build_connect_args` is the single mapping.
- Map MQTT onto `craftainer_crud.config.MQTTConfig` with its TLS options (`MQTT_CA_FILE`,
  `MQTT_CLIENT_CERT`, `MQTT_CLIENT_KEY`) and `MQTT_ALLOW_INSECURE`. Production still requires
  TLS, a username and a password, and now also refuses `MQTT_ALLOW_INSECURE`. The port
  defaults to 8883 with TLS and 1883 without.
- Run the dev broker as production does: TLS listener only, `allow_anonymous false`, a
  password file built from `mqtt.env` at start, and a self-signed certificate written once by
  a one-shot service into a volume the app mounts read-only and trusts through `MQTT_CA_FILE`.
- Keep the library's stream limits at their defaults (`SSE_MAX_STREAMS_PER_CALLER=5`,
  transient sessions) and expose them as settings. Durable sessions
  (`SSE_DURABLE_SESSIONS=true`) stay a host opt-in; the tests that prove resumption enable it.
- Build Hero's owner scope from the token alone (`get_hero_owner_scope`) and pass it as the
  router's `scope_dependency`, so `GET .../events` holds no database session for the life of the
  stream. A token without a usable `sub` is refused with 401 (`invalid_token`) before any
  `OwnerScope` exists.
- Close event delivery on shutdown with `close_event_publishers()`, which waits for the
  after-commit deliveries still in flight, then disconnects the shared MQTT publisher.
- Read the analytics request signals with the library's `from_headers`.
- Leave `GET /health/ready` caching to the library (1 s by default) and expose
  `HEALTH_READY_CACHE_TTL_SECONDS`.

## Consequences

- Running the app, or the image, without `MODE` fails at import with `mode: Field required`.
  Anyone who relied on the image's `MODE=production` default must now pass it.
- A migration that used to connect in plaintext now fails if `POSTGRES_SSLMODE` demands TLS
  the database does not offer, and a slow DDL statement can hit `DB_COMMAND_TIMEOUT`.
- The devcontainer needs a rebuild (or `docker compose up`) for the new broker, volume and
  environment. Anything else that talks to the dev broker needs TLS, the credentials in
  `mqtt.env` and the certificate in the `mqtt-tls` volume.
- Events are published after the commit, in a background task, and a failure is logged and
  counted rather than failing the request. A test that creates records through a short-lived
  event loop must drain deliveries on that loop (`drain_event_deliveries()`).
- `Analytics-Consent` is still asserted by whoever calls the API. Only the BFF may set it, and
  it must strip the header from untrusted traffic; the library documents the same.
