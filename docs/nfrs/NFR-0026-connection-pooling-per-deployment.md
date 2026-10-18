# NFR-0026. Connection pooling is per-deployment configuration, within the connection budget

## Status

Proposed

## Attribute

Performance / scalability.

## Description

This requirement supersedes
[`NFR-0016`](NFR-0016-no-connection-pooling-tradeoff.md) (no pooling).
The service shall:

- choose its database pool only through `DB_POOL_MODE` (`null`, `local`
  or `external`), read from the environment per `NFR-0017`;
- default to `null` (`NullPool`), and use `null` in tests, `dev` and
  `mock`, because a pooled asyncpg connection cannot survive tests that
  mix event loops;
- in `local` mode, keep replicas x workers x (`DB_POOL_SIZE` +
  `DB_MAX_OVERFLOW`) below Postgres's `max_connections` minus reserved
  slots and headroom for migrations and admin sessions;
- in `external` mode, use `NullPool` with unique prepared-statement
  names, for PgBouncer in transaction mode;
- spend at most `TBD` CPU ms/request at the 1 vCPU / 2 GB reference
  budget and 25 users in `local` mode, measured against `null`.

## Source

Developers and operations, preparing a deployment that autoscales.
Detailed by
[`ADR-0022`](../adrs/0022-db-pool-mode-per-deployment.md); measurement
method from
[`ADR-0019`](../adrs/0019-per-pr-benchmarks-and-fixed-load-acceptance.md).

## Verification

Unit tests that each mode builds the right pool class and `connect_args`;
an integration test of `local` against the devcontainer's Postgres inside
one event loop; the e2e suite run with `DB_POOL_MODE=local`; the
null-vs-local comparison with the `tests/perf/` harness before this
requirement moves to Accepted. `external` is verified by live test on the
first deployment behind a pooler. `NFR-0024`'s ceilings still apply to
every mode.
