# Template conventions

Everything about this repository's structure, tooling, and workflow that's
identical across every instance of this template — as opposed to the root
`README.md`'s short, instance-owned preface. See `../CLAUDE.md`'s "Keeping
this file current" for where a new convention belongs.

## Contents

- `.devcontainer/` — the devcontainer setup; see its `README.md`.
- `.github/` — CI and release workflows; see its `CONTENTS.md`.
- `.vscode/` — editor settings, tasks, launch config; see its `README.md`.
- `.claude/` — Claude Code CLI project config; see its `README.md`.
- `.mcp.json` — project-scope MCP servers not covered by a
  `.claude/settings.json` plugin; see `.claude/README.md`.
- `src/` — the application source; see its `README.md`.
- `alembic/` / `alembic.ini` — database migrations; see
  `alembic/README.md`.
- `tests/` — automated tests, split into `unit/`, `integration/`,
  `e2e/` (Playwright), and `perf/` (Locust) suites; see its `README.md`.
- `scripts/` — the Dockerfile's per-stage setup scripts; see its
  `README.md`.
- `docs/` — knowledge about what the app does; this file is the one
  exception, documenting the template itself rather than product/domain
  knowledge.
- `.secrets/` — local secret files, never committed; see its `README.md`.
- `Dockerfile` — three build stages: `develop`, `builder`, `runner`.
- `compose.yml` — runner-image smoke-test stack (distinct from
  `.devcontainer/compose.yml`); see `.github/workflows/README.md`'s
  `smoke.yml` entry.
- `pyproject.toml` / `uv.lock` — dependencies, managed with `uv`, pinned
  to exact patch versions.
- `.pre-commit-config.yaml` — git hooks, run by `prek` or `pre-commit`.
- `CLAUDE.md` — the AI-assisted coding workflow Claude Code follows in
  this repository; general conventions live in this file and each
  directory's own `README.md` instead.

## Getting started

1. Open this folder in a devcontainer (VS Code: "Reopen in Container" —
   `.vscode/extensions.json` recommends the extension that offers this —
   or any tool that reads `.devcontainer/devcontainer.json`). This starts
   the app alongside Postgres, RustFS (S3), Redis, Keycloak (OIDC), and a
   Selenium container Playwright drives remotely for e2e tests; installs
   dependencies; and installs the git hooks, all via `postCreateCommand`.
2. Run the app: `uvicorn app.main:app --reload --host 0.0.0.0`, or use
   the "FastAPI: api" launch config to run it under the debugger. Startup
   applies any pending Alembic migrations automatically — see
   `src/app/README.md`'s "Alembic migrations".
3. Health check: `curl localhost:8000/health/live` (liveness) or
   `curl localhost:8000/health/ready` (readiness — checks Postgres,
   Redis, S3, and the OIDC provider). `curl localhost:8000/crud/v1/heroes/v2/json`
   is a worked example CRUD resource (see `src/app/README.md`'s "Example
   CRUD resource: Hero"). `/protected` needs a bearer token from Keycloak —
   see `.devcontainer/stack/keycloak/README.md`.

Without a devcontainer: install [`uv`](https://docs.astral.sh/uv/), export
your own `DATABASE_URL` / `S3_ENDPOINT_URL` / `S3_ACCESS_KEY` /
`S3_SECRET_KEY` / `REDIS_URL` / `OIDC_ISSUER_URL` / `OIDC_AUTHORIZATION_URL` /
`OIDC_TOKEN_URL` / `OIDC_CLIENT_ID` (see `src/app/config.py` for the
defaults), then
`uv sync --extra dev` and run uvicorn the same way. Run
`uv run prek install` once to enable the git hooks.

## Checks

`ruff` (lint + format), `mypy --strict`, `pytest`, and `pip-audit`
(dependency vulnerabilities, run against exactly what `uv.lock` resolves)
are all configured to fail on any violation — see `pyproject.toml`.
`pytest` also fails below 100% coverage of `src/app`, for both the
default run (`tests/unit` + `tests/integration`) and `uv run pytest
tests/e2e`. `.github/renovate.json` opens a weekly update PR for Python
dependencies, GitHub Actions, and every Dockerfile/compose image tag. Run
everything at once with:

```bash
uv run prek run --all-files --hook-stage manual
```

If a rule produces a false positive, silence that one line with a
justified `# noqa: <code>` rather than loosening the project-wide
configuration. Every function (including tests, `__init__`, and dunder
methods) gets a one-line docstring stating what it does — ruff's
`D100`–`D107` enforce this; see "Code style" below for what the
docstring should actually say.

Hooks are defined once in `.pre-commit-config.yaml` and run by
[`prek`](https://prek.j178.dev/) (a faster, drop-in-compatible
reimplementation of `pre-commit`, already a `dev` dependency — the
classic `pre-commit` CLI reads the same config file if you prefer it).
Fast, basic checks run on commit; slower, extensive checks (mypy,
pytest, `uv lock --check`) run on push. Every hook except the
commit-message check also carries the `manual` stage, so the command
above runs everything else at once. `.vscode/settings.json`'s
`git.commandsToLog` surfaces a failing hook's output in VS Code's Git
output channel immediately, instead of only on request.

Commit messages are checked separately: every commit message must
follow [Conventional Commits](https://www.conventionalcommits.org/),
enforced by the `conventional-pre-commit` git hook at the `commit-msg`
stage — an improperly formatted message is rejected before the commit
is created. This can't be run via the `manual` stage like the other
hooks (see the comment in `.pre-commit-config.yaml`); the only way to
check it is to actually commit.

CI (`.github/workflows/checks.yml`) runs the same `--hook-stage manual`
command, inside the devcontainer itself, on every push and pull request
— as an `amd64`/`arm64` matrix, both legs native (no QEMU). `smoke.yml`
runs the same matrix against the built `runner` image itself.
`.github/workflows/release.yml` is triggered manually to cut an
alpha/beta/rc/full release with an auto-generated changelog and both
arch's built images attached (and optionally pushed to an OCI registry
as one multi-arch manifest) — see `.github/workflows/README.md`.
`.github/workflows/perf.yml` runs
the `tests/perf/` Locust load test against the `runner` image on
`workflow_dispatch` and a weekly schedule (not per-PR — see
`docs/adrs/0010-locust-for-load-testing.md`).

## Template sync

Once instantiated, a repo created from this template can pull in later
template fixes/improvements via `.github/workflows/template-sync.yml`
(itself template-owned, `replace`-tier): on a schedule (cadence set by
the `TEMPLATE_SYNC_INTERVAL` repository variable, `weekly` or `monthly`)
or on demand, it diffs the instance against the template's latest tagged
release, per `.github/template-sync-manifest.yml`'s three tiers
(`replace`, `ignore`, `merge` — see that file's header), and opens a PR
with the result. It never pushes directly or auto-merges; a genuine
`merge`-tier conflict is left with `<<<<<<<` markers for a human to
resolve. An instance that predates this workflow bootstraps its
`.github/template-sync-state.json` via the workflow's manual
`initial_sync_tag`/`template_repo` inputs first.

## Versions and config

Every version and config value is defined in exactly one place; nothing
duplicates or re-pins it elsewhere:

- Python/Debian base image versions: the `PYTHON_VERSION`/`DEBIAN_VERSION`
  `ARG` defaults at the top of the `Dockerfile`. `.devcontainer/compose.yml`
  does **not** pass matching `args:` — the Dockerfile's own defaults are
  authoritative because it's the file closer to where they're used. To
  change them, edit the `Dockerfile`, not the compose file. `PYTHON_VERSION`
  is a single exact-patch pin shared by all three stages: `builder`/`runner`
  use it directly as the `python:${PYTHON_VERSION}-slim-${DEBIAN_VERSION}`
  base image, while `develop` (based on the generic
  `mcr.microsoft.com/devcontainers/base` image, which carries no Python of
  its own) has `develop.sh` install that same version via `uv python
  install`, so all three stages run identical interpreters.
- Python package versions: `pyproject.toml` / `uv.lock`. Dependencies are
  managed with `uv` — use `uv add <package>` / `uv sync` rather than
  editing the dependency lists by hand or invoking `pip` directly.
  All development-only tooling — linters, type checker, test runners,
  Playwright — lives in the single `dev` optional-dependencies group
  rather than split across several groups, since it's all
  development-related; if a future group needs another group's packages,
  reference it as a self-referential extra (e.g. `"template-fastapi[dev]"`,
  per PEP 621) instead of re-pinning the same package a second time.
- Everything else pinned (base images, Actions, hook revisions): pinned
  once, at its single point of use, to an exact patch version — never a
  floating range or `latest` — so Renovate can bump them one at a time and
  the diff shows exactly what changed.

`ruff`, `mypy`, and `pytest` all point their cache dirs at
`/home/vscode/.cache/<tool>` (set once each, in `pyproject.toml`'s
`[tool.ruff]`/`[tool.mypy]`/`[tool.pytest.ini_options]`) instead of the
project root. Same reasoning as not bind-mounting the venv (see
`.devcontainer/README.md`'s "Don't" section): a cache inside the
bind-mounted `/workspace` gets scanned file-by-file by host
antivirus/malware tools on Windows and is painfully slow to write to. A
new tool with its own on-disk cache follows the same pattern.

## Code style

Every file gets a brief header stating what the file *is for* — one
line, sometimes two: a leading comment for most formats, a module
docstring for Python (also required by ruff's `D100`). Never describe
the file's contents in the header; that's what reading the file is for.
Markdown files' own title/opening line already serves this purpose. A
format with no comment syntax (`.json`) documents itself via the
directory's `README.md` instead.

A comment earns its place by saying something the code/config next to
it can't: *why* it's written this way, a non-obvious consequence, or a
constraint that isn't visible locally. Don't add a comment that just
restates what the following line already says in code — if removing a
comment loses no information, remove it. Every existing comment in this
repository follows this rule; keep new ones held to the same bar.

## Do

- Read `CLAUDE.md` and the `README.md` of every directory on the path to
  whatever you're changing before you change it.
- Open this repo in the devcontainer rather than assembling the
  toolchain by hand — it's the one environment this template guarantees.

## Don't

- Commit a `.env` file, or read one from application code — configuration
  lives in the compose files; secrets live in `.secrets/`.
- Add a `ports:` mapping or a `networks:` block to any file under
  `.devcontainer/` — see `.devcontainer/stack/README.md`'s "Devcontainer
  stack pattern" section for how host access and inter-service
  networking are handled instead.
