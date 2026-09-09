# src/

Source layout for the installable package.

- `app/` — the FastAPI application package (`app.main:app`); see its own
  `README.md`.
- `crud/` — the generic CRUD framework `app`'s resource packages build
  on (router factories, interface, repositories, model/view bases); see
  its own `README.md`.

## Keeping the system design doc current

A change to the general system design (a new subpackage, changed
layering/import order, a new cross-cutting flat module) makes
`../docs/system-design.md` stale — update it in the same change.

## Do

- Add new top-level modules as their own package under `src/`, each with
  its own `README.md`.
- Keep `pyproject.toml`'s `[tool.hatch.build.targets.wheel] packages`
  list in sync with what's actually here.

## Don't

- Import from `tests/` — dependencies point one way.
- Put fixtures, sample data, or documentation here — those belong in
  `tests/` or `docs/`.
