# tests/perf/

Locust load test -- the fourth, independent suite alongside `../unit/`,
`../integration/`, and `../e2e/` (see `../README.md`). Not `pytest`-based
at all: Locust has its own headless runner, so this directory is never
collected by a plain `pytest` run (nor by `uv run pytest tests/e2e`) and
is never included in `--cov` -- see `docs/adrs/0010-locust-for-load-
testing.md` for why.

Unlike `../e2e/`, which drives the devcontainer's own `dev`/`mock`
processes, this suite targets the `runner`-stage image (`compose.yml` at
the repo root, `MODE=production`, the same image `../../.github/workflows/
smoke.yml` and `release.yml` ship) over its real Postgres/Redis/S3/
Keycloak backing services -- profiling a reload-enabled, debugger-attached
`dev` process, or `MODE=mock`'s in-memory fakes, would misrepresent
production latency and skip the real database round trips this suite
exists to catch a regression in (see `docs/nfrs/NFR-0016-no-connection-
pooling-tradeoff.md` and `docs/nfrs/NFR-0024-api-latency-and-throughput-
targets.md`, the requirement this suite verifies).

`locustfile.py` scripts the worked example
(`/crud/v1/heroes/v2/json` list/create/get/update/delete, weighted toward
reads) plus `/health/live`, logging in against the real dev-realm
Keycloak (password grant, same convention as `../e2e/conftest.py`'s
`access_token` fixture) since `POST /mock/token` is only mounted under
`MODE=mock`, which this suite deliberately doesn't run under.

## Do

- Run it from the devcontainer's own terminal, against the `runner`
  image's stack:

  ```bash
  docker compose -f compose.yml up -d --build --wait
  uv run locust -f tests/perf/locustfile.py --headless \
      --host http://localhost:8000 \
      --users 50 --spawn-rate 5 --run-time 2m \
      --csv tests/perf/.results/run --html tests/perf/.results/run.html \
      --exit-code-on-error 1
  docker compose -f compose.yml down --volumes --remove-orphans
  ```

  `--exit-code-on-error` makes Locust exit non-zero if any request errors;
  `locustfile.py`'s own `quitting` event listener additionally fails the
  run if any endpoint's p95 latency exceeds `NFR-0024`'s ceiling
  (Locust has no built-in latency-threshold flag).
- Reuse `app.config.get_settings()` for the OIDC token/client-id values
  (as `locustfile.py` already does) rather than hardcoding Keycloak's
  URL a second time.

## Don't

- Import from `../unit/`, `../integration/`, or `../e2e/`, or vice versa
  -- same independence rule as the other three suites (`../README.md`).
- Run this against the devcontainer's own `dev` `uvicorn --reload`
  process, or with `MODE=mock` -- see above for why that would
  misrepresent the numbers this suite measures.
- Add this directory to `pyproject.toml`'s `addopts`/coverage config --
  it isn't `pytest`-collected and never will be.

## Resource sampling and profiling

- `../../compose.perf.yml` is a perf-only override that caps `api` at
  `cpus: "1"` / `mem_limit: 2g` (the reference budget capacity numbers refer
  to) and grants it `SYS_PTRACE`; backing services stay uncapped. Layer it
  with `docker compose -f compose.yml -f compose.perf.yml up -d --build --wait`.
- `stats.py` samples a container's CPU and RSS via `docker stats --no-stream`
  while a run is in progress, then writes a JSON file with the samples and a
  summary (mean/p95/max CPU, mean/max memory) when stopped:

  ```bash
  uv run python tests/perf/stats.py --container <api-container> \
      --interval 2 --out tests/perf/.results/stats.json &   # SIGINT/SIGTERM or --duration ends it
  ```
- `profile.sh [-d SECONDS] [-c CONTAINER]` records a py-spy speedscope
  profile of the server (PID 1 in the container) into `.results/`. The runner
  image has no py-spy and must not gain one, so the script copies the dev
  venv's `py-spy` binary into the container with `docker cp` and runs it
  there as root; `SYS_PTRACE` from `compose.perf.yml` permits the attach.
  It uses `--nonblocking` so sampling doesn't pause the app under load. Run it
  during a capacity run's hold phase, and open the file in speedscope.
