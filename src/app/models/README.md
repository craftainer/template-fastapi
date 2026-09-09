# app/models/

The Model layer: each resource's own SQLAlchemy ORM model. The generic
declarative base, record-lifecycle mixins, and shared revision model
live in `../crud/models/` instead — see its own `README.md`.

- `hero.py` — the example `Hero` model, subclassing `crud.models.base.
  IdentifiedBase` and opting into `crud.models.mixins`' record-lifecycle
  mixins; see `../README.md`'s "Example CRUD resource: Hero".

## Do

- Subclass `crud.models.base.IdentifiedBase`, not `crud.models.base.Base`
  directly, unless a model genuinely doesn't have a single-column integer
  `id` primary key.
- Add a migration after adding or changing a model: `uv run alembic
  revision --autogenerate -m "..."` — see `../../../alembic/README.md`.

## Don't

- Import from `app.views`, `app.controllers`, or `app.health` — see
  `../README.md`'s "Layering" section. Importing from `crud.*` is fine —
  a resource's model builds on the generic base/mixins there.
- Add generic, resource-agnostic model code here — that belongs in
  `../crud/models/` instead.
