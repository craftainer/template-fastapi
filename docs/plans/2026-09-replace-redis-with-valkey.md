# Replace Redis with Valkey for licensing

## Status

Draft

## Goal

`.devcontainer/stack/redis/compose.yml` pins `redis:7.4.11-alpine`.
Redis Ltd. relicensed the Redis server away from BSD-3-Clause starting
with 7.4, to a dual RSALv2/SSPLv1 license — source-available, but not
OSI-approved open source, and it carries usage restrictions (e.g. around
offering it as a managed service) this template shouldn't force onto
every project instantiated from it. Swap to Valkey, the Linux
Foundation's BSD-3-Clause fork (drop-in protocol-compatible, backed by
AWS/Google/Oracle among others), so the stack has no non-OSI-approved
licenses in it. This is unrelated to `2026-09-add-crud-sse.md`, which
was raised alongside this concern but deliberately uses a separate new
service (MQTT) rather than extending this app's Redis usage — this plan
covers only Redis's one existing consumer, `app/rate_limit.py`'s
`Limiter`.

## Approach

1. `.devcontainer/stack/redis/`: rename to `valkey/` (or keep the
   directory name `redis/` if renaming churns too much elsewhere —
   decide when starting this, not here) and change the image to
   `valkey/valkey:8-alpine` (pin an exact patch version the way
   `redis:7.4.11-alpine` was pinned, not a floating `8-alpine` tag).
   Command/healthcheck stay the same shape (`valkey-server
   --appendonly yes`, `valkey-cli ping` — Valkey ships CLI binaries
   under its own name, not `redis-cli`, so update the healthcheck
   command specifically).
2. `app/rate_limit.py`/`app/config.py`: no code change expected —
   `redis-py` (the Python client, MIT-licensed, unaffected by this)
   speaks the same wire protocol Valkey implements; `Settings.redis_url`
   and its `redis://` scheme stay as-is (it's a protocol name, not a
   product name).
3. Update `.devcontainer/stack/redis/README.md` (or its renamed
   equivalent) to describe Valkey instead of Redis, and note why.
4. Verify: `docker compose up` brings the renamed/re-imaged service up
   healthy, then run the existing `tests/unit/test_rate_limit.py` and
   anything in `tests/e2e` that exercises rate limiting against it — no
   behavior change expected, this is a pure infrastructure swap.
5. Fold the "why" into a short ADR
   (`docs/adrs/0013-valkey-over-redis-licensing.md` — coordinate the
   number with whichever of this plan or `2026-09-add-crud-sse.md`'s own
   ADR lands first) rather than leaving the reasoning only in this plan
   file.

## Open questions

- None currently — this is a mechanical swap once the ADR is written.
</content>
