# Add HTTP SSE streaming to the generic CRUD interface

## Status

Draft

## Goal

Let a client subscribe to a resource's create/update/delete/restore
activity in real time over a `GET <prefix>/events` Server-Sent Events
stream, as an opt-in capability of the generic CRUD interface — the same
shape as the existing opt-in hooks (`OwnerScope`, `RevisionSink`) rather
than a bespoke per-resource endpoint. Demonstrated on Hero, matching how
every other opt-in capability has been rolled out. A subscriber must not
silently miss events across a brief disconnect — see "Delivery
guarantee" below, which is why this doesn't use Redis pub/sub (fire-and-
forget, no replay) and doesn't reuse this app's existing Redis service at
all.

## Transport: MQTT (new stack service), not Redis

- **New devcontainer stack service**: `.devcontainer/stack/mqtt/`
  running Eclipse Mosquitto, following the existing pattern in
  `.devcontainer/stack/README.md` (its own `compose.yml` + `README.md`,
  a `healthcheck:`, added to `../compose.yml`'s `include:` list and the
  `api` service's `depends_on:`, no `ports:`/`networks:` block). Config
  needs persistence enabled (`persistence true` + a volume, mirroring
  `redis-data`) — required for the delivery guarantee below.
- **Licensing**: Eclipse Mosquitto is dual EPL-2.0/EDL-1.0, both OSI-
  approved open source — resolves the concern raised against this app's
  existing `redis:7.4.11-alpine` image (Redis Ltd.'s dual RSALv2/SSPLv1
  license as of 7.4, source-available but not OSI-approved). That
  existing Redis service backs `app/rate_limit.py`'s `Limiter` only and
  is unrelated to this feature — its own licensing fix (swap to Valkey)
  is tracked separately in
  `2026-09-replace-redis-with-valkey.md`, not folded into this plan.
- **App-side client library**: `aiomqtt` (MIT-licensed, asyncio-native
  wrapper over `paho-mqtt`, itself dual EPL-2.0/EDL-1.0) — add to
  `pyproject.toml`. Prefer this over a raw `paho-mqtt` callback-based
  client since the rest of this codebase's I/O is async throughout.
- Author a short ADR (`docs/adrs/0013-mqtt-for-crud-events.md`) recording
  this choice — MQTT with persistent sessions + QoS 1 over Redis pub/sub
  (no replay), Redis Streams (would keep everything on the existing
  Redis image, but doesn't remove the licensing question and is a
  heavier lift on top of an already-licensing-flagged service), and DB
  polling (latency + load) — before or alongside implementation.

## Delivery guarantee ("a subscriber must not miss events")

Plain SSE has no built-in exactly-once/at-least-once semantics beyond a
`Last-Event-ID` header a client may resend — the guarantee has to come
from the MQTT side:

- Each SSE subscriber is issued a stable identifier on first connect
  (a `subscriber_id`, returned e.g. as the stream's first event) that
  the client passes back (query param or `Last-Event-ID`) on
  reconnect.
- The server maps that `subscriber_id` to a **persistent MQTT
  session**: `clean_start=False` with a client id derived from
  `subscriber_id`, subscribed at **QoS 1** to `crud-events/<resource>`.
  Because the session is persistent, the broker queues messages
  published while that client id is disconnected (e.g. the browser tab
  closed, the SSE connection dropped) and delivers them once the same
  client id reconnects — this is what makes "briefly offline, no
  missed events" hold, not anything SSE itself provides.
- Bound the broker-side queue per persistent session
  (`max_queued_messages`/`max_inflight_messages` in `mosquitto.conf`,
  plus a `message_expiry_interval` — this isn't unbounded retention
  like a log, it protects a subscriber gone for a bounded window, not
  forever) — document the chosen limits in the ADR.
- This guarantee is scoped to **QoS-1, persistent-session reconnects
  with the same `subscriber_id`** — a client that discards its
  `subscriber_id` and connects fresh gets no replay, by design (there's
  no infinite backlog). Say this explicitly in the FR (see docs below)
  so it isn't read as an unbounded guarantee.

## Approach

1. **`EventSink` hook in `app/interfaces/base.py`**, mirroring
   `RevisionSink`/`RepositoryRevisionSink`'s existing shape:
   - `EventSink` `Protocol`: `async def publish(self, *, resource: str,
     record_id: int, action: str, snapshot: dict[str, Any]) -> None`.
   - `MQTTEventSink`: concrete adapter wrapping an `aiomqtt.Client`,
     publishing a small JSON envelope (`resource`, `record_id`,
     `action`, `snapshot`, timestamp) to `crud-events/<resource>` at
     QoS 1.
   - `CRUDInterface.__init__` gains `events: EventSink | None = None`
     (default `None` — unchanged behavior, same opt-in shape as
     `revisions`). Fire it after every successful mutation `revisions`
     already covers (`create`/`update`/`update_many`/`delete`/
     `delete_many`) **and** `restore`/`restore_many`, since a subscriber
     watching visibility changes cares about restores too — note in the
     ADR/docstring that this is deliberately broader than `revisions`'
     scope, and why.

2. **`MODE=mock` support**: add `build_event_sink_provider(resource:
   str)` to `app/interfaces/dependency.py`, mirroring
   `build_repository_provider`'s branch — `MODE=mock` gets an
   `InMemoryEventSink` (an `asyncio.Queue`-fan-out per resource, built
   once and shared, matching how `InMemoryRepository` is built once and
   shared) instead of `MQTTEventSink`, so the whole stack keeps working
   with zero containers under `MODE=mock`. This sink is necessarily
   best-effort (no broker, no persistent sessions) — the delivery
   guarantee above only applies to the real MQTT-backed path; say so in
   the FR.

3. **Route: `build_json_router` gets a new optional
   `event_source_dependency` parameter** (same
   `Annotated[EventSource, Depends(...)]` shape as `crud_dependency`,
   where `EventSource` is a small `Protocol` for the subscribe side).
   When passed, adds `GET <prefix>/events`:
   - Accepts an optional `subscriber_id` (query param, or read back from
     `Last-Event-ID`) — absent means "issue a new one," present means
     "resume this persistent session."
   - Returns a `StreamingResponse` with `media_type="text/event-stream"`,
     yielding `id: <subscriber-assigned sequence>\ndata: <json>\n\n`
     lines, plus a periodic `: keep-alive\n\n` comment (interval
     configurable via a new `Settings` field, default ~15s) so
     intermediary proxies/load balancers don't time out an idle
     connection.
   - Ends the stream on client disconnect (`await
     request.is_disconnected()` checked between yields) — the
     underlying MQTT session stays persistent/subscribed independent of
     this, per "Delivery guarantee" above.
   - Gated by the same `ReadRoles` dependency the resource's `GET` list
     route already uses — streamed data is exactly what a plain `GET`
     would eventually reveal anyway.
   - JSON-only for now, matching how the other record-lifecycle routes
     (`/clone`, `/draft`, `/publish`, `/restore`, `/revisions`) are
     JSON-only — no XML/web equivalent.

4. **Wire it up on Hero** (`crud_1/heroes/heroes_v2.py` only, not the
   deprecated `v1` sibling — same rollout pattern as the other
   lifecycle mixins): `get_hero_crud` passes an `events=` sink built via
   `build_event_sink_provider("hero")`, and `heroes_v2.py`'s
   `build_json_router` call passes the matching
   `event_source_dependency` so `GET /crud/v1/heroes/v2/json/events`
   exists.

5. **Tests**:
   - `tests/unit/interfaces/test_base.py`: `EventSink.publish` is
     called with the right `action`/`snapshot` for each mutating method,
     the same way existing `revisions` tests check `RevisionSink.record`
     calls.
   - `tests/unit/controllers/test_crud_router.py`: the `/events` route
     exists, requires the same role as `GET`, and streams using
     `InMemoryEventSink` under `MODE=mock`.
   - `tests/integration/crud_1`: an end-to-end case against the real
     Mosquitto service that (a) opens the SSE stream, disconnects
     mid-stream, performs a mutation while disconnected, reconnects with
     the same `subscriber_id`, and asserts the missed event is still
     delivered — this is the test that actually proves the delivery
     guarantee, not just that events flow while connected. Needs an
     async streaming client (`httpx.AsyncClient` with `stream=True`)
     rather than the synchronous `TestClient` used elsewhere.

6. **Docs to update once implemented** (fold into these rather than
   leaving this plan file around, per `docs/plans/README.md`):
   - `docs/adrs/0013-mqtt-for-crud-events.md` (new, per "Transport"
     above).
   - `docs/frs/FR-00NN-crud-event-stream.md` (new), explicitly scoping
     the delivery guarantee (QoS-1/persistent-session reconnect only,
     bounded queue, no guarantee for a discarded `subscriber_id`).
   - `src/app/interfaces/README.md`: new `EventSink`/`EventSource`
     paragraph, same shape as the existing `RevisionSink` one.
   - `src/app/controllers/README.md`'s "Generic CRUD router factories"
     and "Record-lifecycle routes" sections: document
     `event_source_dependency` and the new route.
   - `src/app/README.md`'s "Example CRUD resource: Hero" /
     "Record-lifecycle mixins" sections, and its "Layering" mermaid
     diagram/import-order list if `interfaces/` now imports `aiomqtt`
     directly (it doesn't change internal `app/` import order, just
     worth a mention).
   - `.devcontainer/stack/mqtt/README.md` (new, per the stack pattern).
   - `src/app/config.py`'s new keep-alive-interval / MQTT connection
     settings need a line in whichever section of `app/README.md`
     documents `Settings` additions.

## Open questions

- Whether `events` broadening beyond `revisions`' scope (adding
  `restore`/`restore_many`) is actually wanted, or whether it should
  match `revisions` exactly for consistency — leaning toward broader
  since restore is externally visible, but worth confirming before
  implementing.
- Exact bounds for the broker-side persistent-session queue
  (`max_queued_messages`, `message_expiry_interval`) — needs a concrete
  number in the ADR, not left as "some bound."
- Whether `subscriber_id` issuance/lookup needs its own small durable
  record (so a server restart doesn't strand a persistent MQTT session
  nothing will ever reconnect to and clean up), or whether Mosquitto's
  own session-expiry config is sufficient on its own.
</content>
