# Add general statistics and trend predictions to the generic CRUD interface

## Status

Done — implemented per this plan (repository/interface/controller/view
layers, XML/web parity, Hero wiring, tests, docs). Per `docs/plans/
README.md`, this file should be folded into an ADR (the linear-regression-
vs-real-ML tradeoff and the XML-events-stay-JSON-payload decision, both
flagged as ADR-worthy in the "Docs" section below) and then removed — left
in place for now since writing that ADR was explicitly scoped out of the
implementation pass as a follow-up.

## Goal

Give every CRUD resource an opt-in way to expose aggregate statistics
(`GET <prefix>/stats`) and a simple trend forecast (`GET <prefix>/predict`),
built generically off a resource's existing view/model — the same way
Archivable/Draftable/Schedulable/Lockable/revisions/events are each one
opt-in flag/param on `build_json_router`, not bespoke per-resource code.

**Scope expanded from the first draft of this plan**: record-lifecycle
routes (`/restore`, `/draft`, `/publish`, `/revisions`, `/events`) currently
exist on `build_json_router` only — `controllers/README.md` and
`crud_router.py` both call this out explicitly as "JSON-only for now".
Per direction, this plan now also brings `build_xml_router`/
`build_web_router` up to parity with `build_json_router`, and the new
`/stats`/`/predict` routes are designed as first-class citizens of all
three from the start rather than JSON-only. That "JSON-only for now"
language in `controllers/README.md`/`crud_router.py` is removed as part of
this work. Wired up on Hero as the worked example across all three
formats, matching how every other opt-in mixin is demonstrated today.

Scope decisions already made (see "Open questions" for what's still open):

- **Statistics** = total count; per-numeric-field min/max/avg/sum; per-
  categorical-field (bool/enum) value distribution; time-bucketed counts
  (day/week/month) over `created_at`; and, for a resource carrying the
  relevant `models/mixins.py` mixin, a lifecycle breakdown (archived/draft/
  locked/scheduled-pending/scheduled-expired counts).
- **Predictions** = a lightweight trend forecast (ordinary-least-squares
  linear regression over the same time-bucketed series `/stats` computes),
  projecting N future buckets — deliberately not a trained ML model per
  resource (no new heavy dependency, no model storage/retraining/versioning
  concerns, consistent with this template's low-dependency style). The
  response is explicit about being a naive linear projection, not a
  guarantee.
- **Opt-in**, mirroring `archivable=True`/`draft_schema=`/`revisions=`/
  `events=`: a resource passes `stats_enabled=True` to
  `build_json_router`/`build_resource_router` to get both routes; a
  resource that doesn't is completely unaffected.

## Approach

### 1. Repository layer (`app/repositories/`)

Add to `Repository[ModelT]` (`base.py`)'s Protocol, alongside `count`:

```python
async def stats(
    self,
    *,
    numeric_fields: Sequence[str],
    categorical_fields: Sequence[str],
    filters: Sequence[FilterClause] = (),
    bucket: TimeBucket | None = None,
    include_archived: bool = False,
    include_unpublished: bool = False,
) -> ResourceStats: ...
```

- `TimeBucket` (new small enum: `DAY`/`WEEK`/`MONTH`) and `ResourceStats`/
  `NumericFieldStats`/`TimeBucketCount`/`LifecycleStats` (new frozen
  dataclasses, same style as `filtering.py`'s `FilterClause`/`SortClause`)
  live in a new `repositories/stats.py`, mirroring how `filtering.py` is
  the shared value-object module both concrete repositories import.
- `SQLAlchemyRepository.stats`: one query for count/min/max/avg/sum per
  numeric field (`sqlalchemy.func`), one `GROUP BY` per categorical field,
  one `GROUP BY date_trunc(bucket, created_at)` for the time series (only
  if `bucket` given), reusing `_where_clauses`/`_visibility_clauses` for
  filter/archived/unpublished handling exactly like `list`/`count` already
  do. Lifecycle counts reuse the same `hasattr(self._model, "archived_at"
  /"is_draft"/"is_locked"/"publish_at")` detection `_visibility_clauses`
  already does — one extra `COUNT(...) FILTER (WHERE ...)` per present
  mixin, single query.
- `InMemoryRepository.stats`: the equivalent computed in Python over the
  same in-memory dict + existing filter-predicate helpers, matching how it
  already parallels `SQLAlchemyRepository.list`/`count`.
- Both implementations detect record-lifecycle mixins via `hasattr`, same
  as the rest of this module — a model without a mixin just gets
  `lifecycle=None`.

### 2. Interface layer (`app/interfaces/`)

`CRUDInterface.stats(...)` — a thin pass-through to
`self._repository.stats(...)`, applying `OwnerScope` read-scoping the same
way `list`/`get`/`count` already do (`owner` + `read_scoped`). This is a
generic operation (like `count`), not resource-specific, so it belongs on
`CRUDInterface` itself per `interfaces/README.md`'s existing "Do"/"Don't".

### 3. Controller layer (`app/controllers/`)

New `controllers/crud_stats.py`, alongside `crud_query.py`/`crud_actions.py`
(shared logic `crud_router.py`'s factories wrap):

- Derives which of a resource's view fields are numeric/categorical by
  reusing `crud_query.field_specs(schema)` (`FieldKind.NUMBER` /
  `FieldKind.BOOLEAN`/`FieldKind.ENUM`) — no new field-classification logic,
  single source of truth stays in `crud_query.py`.
- Parses `/stats`'s `?bucket=day|week|month` (optional; time series omitted
  if absent) into `TimeBucket`.
- Parses `/predict`'s `?field=&periods=&bucket=` (all optional; `field`
  omitted means "forecast record count over time", matching how `/stats`'s
  time series defaults to count) and validates `periods` is a small,
  bounded positive int (e.g. 1–52 — cap to prevent an absurd request).
- `forecast(series: Sequence[TimeBucketCount], periods: int) -> list[Prediction]`
  — plain ordinary-least-squares over `(bucket_index, value)` pairs, stdlib
  only (`statistics`/basic arithmetic, no numpy/scikit-learn). Raises a
  typed error (→ 422 "not enough data", same pattern as other
  `RequestValidationError` uses in this layer) when fewer than 2 buckets of
  history exist.

`crud_router.py`: `build_json_router` gains one new opt-in param,
`stats_enabled: bool = False` (default-off, matching `archivable`). When
`True`, two routes are added:

- `GET <prefix>/stats?bucket=&include_archived=&include_unpublished=` — 200
  with count/numeric/categorical/time-series/lifecycle, built via
  `crud_stats.py` + `CRUDLike.stats`. Gated by the same `read_roles`
  dependency as the plain `GET` list route.
- `GET <prefix>/predict?field=&periods=&bucket=` — 200 with the historical
  series' last bucket, the requested `periods` of projected values, and the
  method name (`"linear_regression"`) so a client never mistakes it for a
  real fitted model; 422 if `field` isn't a numeric field of the schema or
  there's insufficient history. Same `read_roles` gate.

### 4. Views (`app/views/`)

New response shapes in a small `views/stats.py` (`ORMView`-adjacent, plain
`BaseModel`s since these aren't ORM-backed): `ResourceStatsView`,
`PredictionView`, plus flat per-item sub-models `NumericFieldStatView`/
`CategoricalValueCountView`/`TimeBucketCountView` (see "XML router" below
for why these stay separate, flat models rather than nesting directly).
Keeps `crud_router.py`'s route bodies thin, matching how `views/bulk.py`
already holds `BulkUpdateResult`/`BulkDeleteResult`.

### 5. XML router (`build_xml_router`) — bring to parity

This is the scope change: today `build_xml_router` only has the original
list/create/get/update/delete shape, and `build_resource_router`'s own
docstring says draft/publish/restore/revisions/events "are JSON-only for
now ... XML/web keep their existing ... shape unchanged." That precedent
is reversed here for all of it, not just the new routes:

- `POST <prefix>/restore` — XML body-less (mirrors JSON: id-or-filters via
  query params only), renders the same `BulkUpdateResult`/single-record
  outcome via `to_xml`, exactly like `update_records_xml`/`delete_records_xml`
  already do for `PATCH`/`DELETE`.
- `POST <prefix>/draft` / `POST <prefix>/publish` — `draft` parses an XML
  body with `_parse_xml_body(..., draft_schema)` (same helper
  `create_record_xml` already uses); `publish` takes `id` as a query param
  (no body), same as JSON. Both render the resulting record via `to_xml`.
- `GET <prefix>/revisions?id=` — renders `list[RevisionView]` the same way
  `list_records_xml` already renders a list: `<revisions>` wrapping
  repeated `<revision>` elements, each `to_xml(r, "revision")`.
- `GET <prefix>/stats` / `GET <prefix>/predict` — `ResourceStatsView`/
  `PredictionView` are hand-assembled XML (not a single `to_xml` call):
  `xml_codec.to_xml` only supports a *flat* model (scalar or flat-list
  fields, per its own module docstring) and stats/predictions are
  naturally nested (per-field aggregates, a distribution, a time series).
  The route follows the same pattern `list_records_xml` already uses for
  a list of records — render each numeric-field/categorical-value/
  time-bucket row as its own flat model via `to_xml`, then concatenate
  those inside wrapping tags (`<numeric-fields>`, `<time-buckets>`, etc.)
  by hand, same string-building style already used for the list route.
  No change to `xml_codec.py`'s own flat-model constraint — this stays
  route-level assembly, matching existing precedent instead of teaching
  the shared codec a new nesting rule that every other resource would
  then have to reason about too.
- `GET <prefix>/events` — **stays a JSON-payload SSE stream even under the
  XML router.** SSE's `data:` line is a transport envelope, not a resource
  representation — treating it as one and running every event dict through
  a new dict→XML path would be new scope with no existing precedent
  (`to_xml` takes a `BaseModel`, and event payloads are plain dicts by
  design — see `interfaces/README.md`'s `EventSink`/`EventSource`
  paragraph). Flagged as an explicit decision, not an oversight — see
  "Open questions" if XML-encoded event payloads are actually wanted.

`build_xml_router` gains the same new params `build_json_router` already
has (`draft_schema`, `archivable`, `revision_repository_dependency` +
`resource`, `stats_enabled`) plus `item_tag`/`list_tag` already has what's
needed for the new flat-row rendering. `build_resource_router` forwards
all of them to both factories identically instead of JSON-only.

### 6. Web router (`build_web_router`) — bring to parity

The web router doesn't talk to the database itself — `render_crud_component_js`'s
generated JS already calls the sibling JSON router (`api_base`) directly
for list/create/update/delete/filters, per its own docstring. So covering
lifecycle records here means extending that generated JS (and
`render_crud_form`'s HTML shell) to add UI for the actions the JSON router
now exposes, gated by the same new boolean/schema params
`build_resource_router` already forwards to `build_json_router` — today
`build_web_router` receives *none* of `archivable`/`draft_schema`/
`revision_repository_dependency`/`event_source_dependency`, which is the
actual gap, not just the new stats/predict routes:

- `archivable=True` → an Archive/Restore row action in the generated list
  UI (`DELETE`/`POST .../restore?id=`).
- `draft_schema` given → a "Save as draft" / "Publish" pair of actions.
- `revision_repository_dependency` given → an expandable "History" panel
  per row, fetching `GET .../revisions?id=`.
- `event_source_dependency` given → the rendered list subscribes to
  `GET .../events` (browser `EventSource`) and live-patches rows instead
  of only refreshing on demand.
- `stats_enabled=True` → a "Stats" panel (numeric aggregates, distribution,
  a simple bar/line rendering of the time series) and a small "Predict"
  control (pick a field + periods, show the projected values) — plain
  HTML/JS, no new charting dependency (a `<table>`/inline SVG is enough,
  consistent with this template's zero-heavy-frontend-dependency style;
  `dataviz`-style charting is available if a richer rendering is wanted
  later, but not required for this plan).

No new FastAPI routes are needed under `/web` itself beyond what already
exists (`/form`, `/components.js`) — everything above is client-side JS
added to `web_components.py`'s `render_crud_component_js`/`render_crud_form`,
calling the (now-present) JSON endpoints. `web_components.py` has no README
of its own today (documented inline in `controllers/README.md`); that
section gets updated instead of a new file created.

### 7. Wire up on Hero

`crud_1/heroes/heroes_v2.py` passes `stats_enabled=True` alongside its
existing `archivable=True`/`draft_schema=`/`revisions=`/`events=`, and
`build_resource_router` now forwards all of these to `build_xml_router`/
`build_web_router` too (today it only forwards to JSON) — Hero stays the
one resource demonstrating every opt-in capability, across all three
formats, per `app/README.md`'s existing "Record-lifecycle mixins" section
(add a new bullet there: "**Statistics/predictions**", and update the
existing bullets to note XML/web coverage instead of JSON-only).

### 8. Tests

- `tests/unit/repositories/test_sqlalchemy.py` / `test_memory.py`: `.stats`
  parity between both backends, including each lifecycle-mixin branch and
  the "model has no mixin" no-op case.
- `tests/unit/controllers/test_crud_stats.py`: query parsing, the OLS
  forecast math (known input → known output, and the insufficient-data
  422 path) — independent of the repository work, can be written in
  parallel per this repo's own "resolve test coverage gaps in parallel"
  convention.
- `tests/unit/controllers/test_crud_router.py`: new XML-router tests for
  restore/draft/publish/revisions/stats/predict (XML round-trip,
  well-formedness of the hand-assembled nested stats/predict bodies).
- `tests/integration`: `/stats`/`/predict` (and the newly-XML-covered
  lifecycle routes) against real Postgres for Hero, both `/json` and `/xml`.
- `tests/e2e`: happy-path hits of the new JSON+XML routes under `MODE=mock`
  and a real run; a Playwright check that the web UI's new
  archive/restore/draft/publish/history/stats/predict controls render and
  work against a live Hero record — this session's `playwright` MCP server
  failed to connect, so that verification couldn't be run live here and
  needs to happen when it's back or by the user directly.

### 9. Docs

Update `app/README.md` ("Record-lifecycle mixins" section, including
removing the "JSON-only" framing), `controllers/README.md` ("Generic CRUD
router factories" section — same removal, plus documenting the new XML/web
coverage and the hand-assembled stats/predict XML shape),
`interfaces/README.md` (`CRUDInterface.stats` alongside `count`), and
`repositories/README.md` (new "Statistics" section alongside "Record-
lifecycle mixins") — each directory's own doc, per this repo's
`CLAUDE.md` convention, not this plan file once the work lands.

Whether this warrants its own ADR (the linear-regression-over-real-ML
tradeoff, and the XML-events-stay-JSON-payload decision, are both
reversible-at-cost design decisions, similar in kind to 0008/0011/0015) is
worth a short one once implemented — captures *why* without bloating any
README.

## Open questions

- Time-bucket boundary semantics (UTC calendar day/week/month vs. rolling
  windows) — recommend UTC calendar buckets via Postgres `date_trunc`,
  matching this app's existing naive-UTC-everywhere convention
  (`app/README.md`), but not yet confirmed.
- Whether `/predict`'s forecast should be able to target a *categorical*
  field's future distribution (not just a numeric field or record count) —
  out of scope for this first pass; can be added later as `field` accepting
  a categorical name too, without changing the route shape.
- Whether `GET <prefix>/events` under the XML router should actually
  XML-encode its event payloads instead of staying JSON — current plan
  keeps SSE payloads JSON everywhere (transport envelope, not a resource
  representation); flag if that's wrong.
- Web UI depth for stats/predict (plain table vs. an actual chart) — plan
  assumes a plain table/minimal inline SVG is enough; say if a richer
  chart is actually wanted, since that changes the frontend work size.
