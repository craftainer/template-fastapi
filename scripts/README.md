# scripts/

Setup logic for each `.devcontainer/Dockerfile` / `Dockerfile` RUN step —
every RUN calls one of these (or loops over a hook directory below), never
a binary directly:

- `develop.sh` — `../.devcontainer/Dockerfile`'s `develop`-stage setup: installs `prek`,
  the Claude Code CLI, `snip` and the GitHub CLI (`gh`), the only tooling this template requires
  regardless of instance language. An instance adds its own language
  runtime/tooling install on top, either by extending this script or
  copying its shape into a second script. Prefer the hook below over
  either.
- `post-create.sh` — the devcontainer's `postCreateCommand`: git
  `safe.directory`, `prek install`, then every `post-create.d/*.sh`.
- `develop.d/`, `post-create.d/` — instance hook directories; see
  `docs/TEMPLATE.md`'s "Instance extension points". template-fastapi's
  own hooks:
  - `develop.d/NN-*.sh` — FastAPI-specific extra develop tooling (apt
    clients, pyright, rustfs CLI, `kcadm`), run after `develop.sh`; each
    pins its own version with a `# renovate:` comment.
  - `post-create.d/NN-*.sh` — devcontainer post-create steps (`uv sync`,
    migrations).
- `builder.sh` — `../Dockerfile`'s `builder` stage tooling setup (apt
  packages, `uv`).
- `builder-sync-deps.sh` / `builder-sync-app.sh` — the `builder` stage's
  two `uv sync` steps, split so a source-only change doesn't invalidate
  the dependency-install layer.
- `runner-setup.sh` — `../Dockerfile`'s `runner` stage user/permission
  setup.
- `runner.sh` — the `runner` stage's entrypoint (starts the app, as PID 1
  via `exec`). `APP_SERVER` picks the server: `uvicorn` (default) or
  `granian`; any other value exits 64 with a message.
  - uvicorn runs with `--loop uvloop --http httptools` (a missing wheel
    fails loudly). Every other tunable is an unset-by-default
    `UVICORN_*` env var that uvicorn's CLI reads natively, e.g.
    `UVICORN_ACCESS_LOG=false`, `UVICORN_PROXY_HEADERS`,
    `UVICORN_BACKLOG`, `UVICORN_TIMEOUT_KEEP_ALIVE`,
    `UVICORN_LIMIT_CONCURRENCY`, `UVICORN_WORKERS`. Note that
    `--limit-concurrency` makes uvicorn answer with its own plain-text 503
    before the app runs, so that response is not RFC 9457 problem details.
  - granian runs `--interface asgi` on the same host/port; tune it with
    `GRANIAN_*` env vars (`GRANIAN_WORKERS`, `GRANIAN_BACKLOG`,
    `GRANIAN_LOOP`, `GRANIAN_LOG_ACCESS_ENABLED`, ...).
  - `GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS` (unset by default) maps to
    uvicorn's `--timeout-graceful-shutdown`. Granian has no such option;
    the closest is `GRANIAN_WORKERS_KILL_TIMEOUT`, which runner.sh sets
    to the same value.
  - `APP_VERSION` / `APP_COMMIT` are baked in by the `Dockerfile`
    `ARG`s (set by `make build`).
- `check-dockerfile-versions.sh` — pre-commit check that
  `../.devcontainer/Dockerfile` and `../Dockerfile` agree on
  `PYTHON_VERSION`/`DEBIAN_VERSION`.

## Do

- Keep each script runnable and idempotent on its own (`bash
  scripts/develop.sh <args>`) so you can debug a stage without a full
  build.
- Take a version as a script argument (see `develop.sh`) rather than
  hardcoding it, when the Dockerfile already defines it as an `ARG` —
  keeps that `ARG` the single source of truth.
- Clean up apt lists / caches at the end of a script that installs
  packages, to keep the resulting layer small.
- Keep this script's own tools pinned to an exact version (a `# renovate:`
  ARG in `../.devcontainer/Dockerfile`) and checksum-verified where the upstream project
  publishes checksums, matching the pattern each install step here already
  follows.

## Don't

- Invoke a binary directly from a Dockerfile `RUN` — add or extend a
  script here instead.
- Install tooling a different stage needs — `runner.sh` in particular
  should stay a plain entrypoint, not a setup script.
- Add a language runtime or stack-specific tool to `develop.sh` — that
  belongs in the instance's own layer (`develop.d/`), not the base
  template's.
