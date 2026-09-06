# app/controllers/

The Controller layer: the generic CRUD router factories every resource
builds on, plus the handful of FastAPI routers with no resource of their
own. A resource's own router (e.g. Hero) lives in `../crud_1/`
instead — see its `README.md`. Sits below `crud_1` and `main` in
`src/app/`'s import order — may import from any other `app/` subpackage,
but only `crud_1`/`main` may import from here (see `../README.md`'s
"Layering" section).

- `health.py` — `/health/live` and `/health/ready`.
- `protected.py` — `/protected`, a minimal example of `Depends
  (get_current_claims)`.
- `audit.py` / `mock.py` — see their own module docstrings.
- `crud_router.py` — the generic router factories (see "Generic CRUD
  router factories" below).
- `crud_actions.py` / `crud_query.py` — the shared id/filter/bulk
  decision logic and the `field__op=value`/`sort=` query-string parser
  `crud_router.py`'s factories wrap; see their own module docstrings.

## RBAC

Add a role requirement to a route with `dependencies=[Depends
(require_roles("editor", "maintainer"))]` from `app.oidc` (see
`../README.md`'s "RBAC" section for the mechanism), or a module-level
`Depends(...)` constant reused across a router's routes — see
`app.crud_1.heroes.heroes_v2`'s `ReadRoles`/`WriteRoles`/`DeleteRoles`.

## Generic CRUD router factories

`crud_router.py`'s `build_json_router`/`build_xml_router`/`build_web_router`
build a resource's list/create/get/update/delete routes (or, for
`build_web_router`, its `/form` + `/components.js` routes) internally, as
closures over the Pydantic views and CRUD dependency passed to them.
`build_resource_router` composes all three into one resource-version's
combined `APIRouter`, mounting each under its own `/json`/`/xml`/`/web`
sub-prefix — `app.crud_1.heroes`'s `heroes_v2.py`/`heroes_v1.py` are
one `build_resource_router(...)` call each, not three separate
per-format router modules; see `../crud_1/README.md`'s "API and model
versioning" and `docs/adrs/0009-...md` for the full path shape. Its own
`prefix` argument should always be `""` — the caller's own resource
package (e.g. `heroes/__init__.py`) is where the real, resource-relative
prefix gets assigned, explicitly, at the `include_router` call that
mounts the returned router. Every `include_router` call in this
repository passes an explicit, non-empty `prefix`, so a route's full URL
can be read off the chain of mount sites alone; see
`../crud_1/README.md`'s "Every mount names its own segment", and its
"Don't" section for why a resource-version router baking its own prefix
in here is bad design. `api_prefix` is separate and still needed as the full absolute
path (e.g. `/crud/v1/heroes/v2`) — it only feeds `build_web_router`'s
`api_base`, which gets baked into rendered HTML/JS at build time and
can't be derived from a later `include_router` call's prefix the way
FastAPI's own routing can. Each factory takes `crud_dependency` as an
`Annotated[app.interfaces.base.CRUDLike[...], Depends(...)]`-shaped value —
`CRUDLike` is a `Protocol` both `CRUDInterface` (current version) and
`CompatCRUD` (deprecated version, see `../crud_1/README.md`'s "API
and model versioning") satisfy structurally, so the same factories build
both.

`crud_router.py`'s `ROUTER_VERSION` constant names a version of these
factories' own route shape/behavior, not any resource's shape — see
`../crud_1/README.md`'s "API and model versioning" for the full
three-axis path scheme this feeds into.

**Record addressing, filtering/sorting, and bulk actions** (`build_json_router`/
`build_xml_router`): a single record is addressed by an `id` query
parameter, not a path segment — `GET/PATCH/DELETE <prefix>?id=5`, 404 if
missing. `id` names the query key regardless of a resource's own id-field
name, the same way every generated route used to name its path parameter
`record_id` before addressing moved off the path. Without `id`, `GET` lists
(optionally filtered/sorted, see
`app.controllers.crud_query`'s module docstring for the `field__op=value`/
`sort=` wire format) and `PATCH`/`DELETE` act in bulk over whatever filters
are given — a request with **no** filters and no `id` is rejected (422 via
`RequestValidationError`) rather than silently acting on every record.
`app.controllers.crud_actions`'s `resolve_list_or_get`/`resolve_update`/
`resolve_delete` implement this id/filter/bulk decision once, shared by both
factories; each wraps the same calls in its own response format (JSON body
vs. an XML-rendered `Response`). Before a bulk update/delete actually runs,
`crud_actions.py` counts how many records the filters match
(`CRUDLike.count`) and refuses the action (400) above
`app.config.Settings.bulk_action_max_matched` (default 1000) — a
technically-non-empty but always-true filter (e.g. `id__gte=0`) would
otherwise still match every row. A bulk action that does run is logged
(`INFO`, actor/path/filters/ids) for auditing, and is itself rate-limited —
see `app/README.md`'s "Rate limiting". A bulk action's response
(`app.views.bulk.BulkUpdateResult`/`BulkDeleteResult`) carries the matched
count and the ids affected, not the full records. `build_json_router` also
serves `GET <prefix>/filters`, the same per-field-type introspection
`crud_query.py` uses to parse, as JSON — the `<resource>-list>` web component
(`app.web_components`) fetches this once to render filter/sort/bulk controls
generically, without either side hardcoding a resource's fields.

**Record-lifecycle routes** (`build_json_router` only — JSON-only for now,
XML/web keep their original list/create/get/update/delete shape):
`?include_archived=true`/`?include_unpublished=true` on the existing `GET`
override the default Archivable/Schedulable exclusion (see
`../repositories/README.md`). `POST <prefix>/clone?id=` is always added
(fully generic, no mixin needed): it builds `create_schema` from the
fields it itself declares, read off the existing record, so a
Draftable/Archivable/Schedulable model's server-assigned fields are never
copied from the source. `draft_schema` (typically a resource's own
all-optional `*Update` view), if passed, adds `POST <prefix>/draft`
(persists with server-assigned lifecycle defaults) and `POST
<prefix>/publish?id=` (re-validates against `create_schema`, 422 naming
any field still missing, then flips `is_draft=False`). `archivable=True`
adds `POST <prefix>/restore`, mirroring delete's own id-or-filters/
single-or-bulk shape (`app.controllers.crud_actions.resolve_restore`,
same rate-limit/`exempt_single_record_action` treatment as the bulk
update/delete routes). `revision_repository_dependency` + `resource`
together add `GET <prefix>/revisions?id=`, a plain query against the
shared `Revision` table (`app.models.revision`) — not routed through
`crud_dependency`/`CRUDLike` at all, since it reads a different model
entirely. `event_source_dependency` (an
`Annotated[app.interfaces.base.EventSource, Depends(...)]`-shaped value,
mirroring `crud_dependency`'s own shape) adds `GET <prefix>/events`: a
`StreamingResponse` (`media_type="text/event-stream"`) of that resource's
create/update/update_many/delete/delete_many/restore/restore_many
activity, gated by the same `read_roles` dependency as the plain `GET`
list route. The route resolves an optional `subscriber_id` query param
(falling back to the standard `Last-Event-ID` header on reconnect), calls
`EventSource.subscribe`, and renders the result via `crud_router.py`'s
private `_sse_events` — which uses `asyncio.wait` on a persisted
`__anext__()` task rather than `asyncio.wait_for` around each keep-alive
tick specifically because `wait_for` would cancel (and tear down) the
underlying event generator on every single keep-alive interval; see
`_sse_events`'s own docstring. See `app.crud_1.heroes.heroes_v2` for all
of the above wired up on Hero, `app/README.md`'s "Record-lifecycle
mixins" section, and `docs/adrs/0015-mqtt-for-crud-events.md` for the
event stream's transport and delivery-guarantee design.

The generated route functions' `crud`/`record` parameters are annotated
with a TypeVar-bound runtime value (e.g. `create_schema`, a `type[CreateT]`
parameter of the enclosing factory) — mypy cannot resolve that statically,
so those specific lines carry a narrow `# type: ignore[valid-type]`/
`# type: ignore[no-any-return]`, justified by `crud_router.py`'s own module
docstring; the factories' own public signatures stay fully strict-typed, so
a caller like `app.crud_1.heroes.heroes_v2` gets normal type-checking on
its `build_resource_router(...)` call.

`build_xml_router`/`build_web_router`'s routes construct and return their
own `Response`/`RedirectResponse` directly (XML bodies, redirects, JS) —
FastAPI does **not** merge a `dependencies=[...]` entry's `response.headers`
mutations (e.g. `app.http_headers.sunset(...)`, see `../crud_1/README.md`'s
"API and model versioning") into a route's own returned `Response`, only into
its own auto-built one, so every such route also takes the injected
`response: Response` and merges it in via `crud_router.py`'s private
`_with_dependency_headers` before returning. Skipping this silently drops
router-level headers on every XML/web route with no visible error — this
bit the deprecated v1 XML/web routes once, before the helper was
introduced.

`build_web_router`'s `/form` POST route parses `Request.form()` generically
(field names aren't known until the factory is called, so a typed
`Form()` parameter per field isn't possible) — it attaches an
`openapi_extra` describing each field as a required string so Swagger UI
still documents the submission shape, rather than showing an undocumented
body.

## Do

- Add a resource-agnostic router-building helper (usable by any future
  resource) to `crud_router.py` — a resource-specific router belongs in
  `../crud_1/` instead, see its `README.md`.
- Add auth to a route with `Depends(get_current_claims)` from
  `app.oidc` — a route with no such dependency is public.

## Don't

- Put persistence or conversion logic directly in a route body — that
  belongs in `app.interfaces`/`app.repositories`; a route should stay a thin
  translation between HTTP and a `CRUDInterface` call.
- Add a resource's own router module here — resources live in
  `../crud_1/` so `controllers/` stays generic, reusable machinery
  only.
