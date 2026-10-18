# Extract crud and observability packages, then improve throughput and observability

## Status

In progress (kickoff 2026-10-17, G0 granted; pre-flight complete 2026-10-18). Baseline commit: `07154b9` (full check suite green). Integration branch: `integration/packages-perf-observability`. Wave 0: W0a done in pre-flight; W0 merged and verified (`b39c026`). Wave 1 in progress.

**Progress (2026-10-17, second orchestrator session):**

- The snip commit blocker didn't recur: check runs, merges and commits went through without the wrapper hook. The decision-log rule (single-line git commands; stop and hand back if refused) still applies.
- `f8b1106` (W0, S1, D1 + fixes) verified green. D2 merged as `c64d678` (one import-block conflict with D1 in `tests/integration/test_health_checks.py`, resolved to D2's imports); suite and smoke stack green. O1 (committed by the user as `1939778`) merged as `829ddc6`: smoke green, e2e coverage 97% as a known gap (Decision log).
- Batch 2 merged and verified: P1 `8e1ee3e`, P2 `f52728b`, P3 `12774d2`, R1 `5962bec`.
- Batch 3 merged and verified: N1 `058d7c0`, V1 `eb81876`, P2b `89f4f60`, M0 `1356a44` (new item, user-approved), then the perf rate-limit threshold fix. Q1 reported; findings feed F1–F3 (copied into the Decision log below). Every suite is green apart from the known e2e gap (now O1 + N1, see Decision log).
- The perf harness works end to end locally: capacity smoke on the capped stack with 0% errors, `max_users_passed` 10, 8 workers, api CPU/RSS embedded. **L1's baseline can start** (it needs a quiet window, no agents running).
- Batch 4 merged and verified: P5 `97173a4`, R2 `74c6a78` (+ e2e pragma fix). Authenticated perf smoke after R2: 0% errors, 8 workers. P5's workflows haven't run yet (they need a push; see Decision log).
- P2c merged and verified (`8817990`). L1 capacity baseline done (Decision log 2026-10-18).
- L1 fixed-load baseline done (Decision log 2026-10-18).
- Wave 2 batch A merged and verified (`f4bd1a6`).
- Wave 2 batches B and C merged; integration branch fully green at `0effb83` (e2e 100%).
- A7 merged and verified (`3b28bc5`).
- **2026-10-18, third orchestrator session:** pre-flight closed by the user (`1890b5e`; `deny` list removal committed as `4fb1ac3`). The suite is green on the rebuilt devcontainer (e2e included). `craftainer/template-python-package` was created from template-base v1.4.0 and marked as a template. Copying the rulesets was **refused by auto mode's classifier**, so it's with the user (cleaned JSON in the orchestrator's scratchpad; Decision log). T1, T2, T3 and B1 are running (local clones under `.claude/worktrees/ext-*`). L1's A/B program was interrupted at c1–c4 x2, c5–c6 x1 (`tests/perf/.results/ab-1110fab/`); it resumes in the next quiet window.
- T1–T3 merged into template-python-package's `integration/scaffold` (19 hooks green) → PR craftainer/template-python-package#2. B1 → PR craftainer/template-base#14, extended with `PYPI_PUBLISH` pass-through (T2 and T3 both found base's `release.yml` never passed it to `make publish`/`release-check`). Both await G-pr; the rulesets still await the user.
- G-pr: template-base#14 and template-python-package#2 merged; rulesets on template-python-package applied by the user. template-base **v1.5.0** released. Sync PRs open: template-fastapi#40 and template-python-package#3, each changing only `release.yml`, the workflows README and the sync state.
- template-python-package#3 and template-fastapi#40 merged (both at template-base v1.5.0). Wave 3 started: `craftainer/tool-crud` and `craftainer/tool-observability` created from template-python-package (public). History imports pushed to `main`: tool-crud `4a7f1dc` (32 commits; `crud_router.py` history follows the rename, 8 commits), tool-observability `99ebdbd` (18 commits; `logs.py` 8 commits). **Rulesets on both are with the user, before any PR merges.**
- Rulesets on tool-crud and tool-observability applied by the user (a single "Protect main" ruleset per repo, the user's choice). L1 paused after 13 valid fixed-load runs (interim results in the Decision log). Running now: K1, K2, A8 (access-log fix), P1c (docker-free sampler).
- A8 and P1c merged here and verified (`6794d38`; e2e's mock leg now runs with the access log off, asserting both states). K1/K2 → PRs craftainer/tool-crud#2 and craftainer/tool-observability#2. The template-python-package v1.0.0 release failed (`uv: not found` on release.yml's bare runner) → fix PR craftainer/template-python-package#4, the same Makefile already in K1/K2. L1 resumed (third runs, the access-log A/B on a `6794d38` image, capacity runs).
- G-pr: template-python-package#4 and tool-observability#2 merged. **template-python-package v1.0.0 released** (sdist, wheel, SBOM; the first real run of the package release contract). tool-crud#2's CI failed on ruff only: K1's local `--all-files` run skipped its untracked new files, the same trap T1 hit. Fixed with no suppressions; CI is now green, including the 100% gate with the integration suite on `compose.instance.yml`'s Postgres. Sync state → template-python-package v1.0.0: on tool-crud#2, and in tool-observability#3.
- **Next:** G-pr tool-crud#2 and tool-observability#3; then G-rel: set `PYPI_PUBLISH=testpypi` per package repo and run `release.yml` for 0.1.0 (TestPyPI dry run), then PyPI; L1 report → X2 numbers; then Wave 4.

## Goal

Raise how much sustained load the `runner` image can serve on fixed
hardware, using only configuration, existing library APIs, and changes
to this repo's own code, never by reimplementing FastAPI, Starlette,
uvicorn, SQLAlchemy, Pydantic or PyJWT internals. Put a measurement
method and CI wiring in place first, so every change below is accepted
or rejected on numbers rather than folklore. Make the app's
configuration and telemetry ready for a later Kubernetes deployment
(HA Postgres operator; OpenTelemetry metrics and traces feeding
Prometheus and similar tools), so it can be observed in production too.
Before any of that, move the generic `crud` package, and `health` grown into a
broader observability package, out
of this repo into their own published Python packages, built from a
new reusable Python package template. All of this lands as one batch
of changes, run as parallel waves of Sonnet 5.5 agents under an Opus
5.5 orchestrator (see "Execution" below).

## Background: what the $12-server challenge showed

Source: "I Asked Expert Programmers to Max Out a $12 Server"
(Arjay McCandless, <https://www.youtube.com/watch?v=QGWKCaglSBI>), and
its submissions repo
<https://github.com/arjaythedev/twelve-dollar-server-challenge> (k6
script in `bench/load.js`, Python entry in
`submissions/python-fastapi-cknutson12/`). Setup: 1 shared vCPU, 2 GB
RAM, in-process SQLite. A user count passes if it holds for 5 minutes
with p95 < 500ms, p99 < 1s and errors < 1%.

Python results:

| Variant | Sustained users |
| --- | --- |
| Original video: FastAPI + Postgres + Nginx | ~2,150 |
| Plain FastAPI + SQLite + uvloop + orjson | ~11,000 |
| Same app, profiled, framework layers stripped (no Pydantic models, no DI, raw `Response`) | ~22,000 (CPU at 91%) |

Techniques that recurred across the fastest submissions in every
language, and whether each one transfers here:

| Technique | Transfers? | Why |
| --- | --- | --- |
| Reuse one DB connection and prepare queries once | **Yes, highest value** | We use `NullPool` (`src/crud/models/base.py`, `NFR-0016`), so every request opens a new asyncpg connection and loses asyncpg's per-connection prepared-statement cache. See Phase 3. |
| Fast event loop and HTTP parser (uvloop, httptools) | Yes, verify only | `uvicorn[standard]` already installs both. Pin them explicitly so a missing wheel fails loudly instead of silently falling back. |
| Serve directly, no Nginx | Already true | `runner.sh` serves uvicorn directly. |
| Strip per-request work the API doesn't need (access log, proxy headers, DI layers) | Partly | Flags and cheap code-level wins, yes. Bypassing FastAPI routing/DI to reach the handler, no: that is reimplementing the framework. |
| Lightweight JSON | Yes, via the framework | FastAPI's docs: with a return type or `response_model`, "Pydantic uses the same underlying Rust mechanisms as `orjson`", while a `response_class`/`jsonable_encoder` path is slower. Make sure hot routes take that path rather than adding orjson. |
| GC tuning (`gc.freeze()` after startup, higher gen-0 threshold) | Yes, cheap | Three stdlib lines. Measure memory and latency together. |
| Database builds the JSON (`json_agg`) | No | Bypasses `crud.views`' `from_attributes` views and the generic CRUD layering (`ADR-0001`, `NFR-0004`). |
| Group commit (batch many requests' writes into one transaction) | No | Needs a custom write queue, and one failed batch fails every waiting request. Reimplements what Postgres does internally. |
| Weaker durability (`synchronous=NORMAL`; Postgres analogue `synchronous_commit=off`) | No | Acknowledged writes can be lost on power loss. |
| Hand-rolled JWT verification, io_uring, custom HTTP parser | No | Out of scope by definition, and a security regression risk. |

## Execution

This plan follows the standing rule in `CLAUDE.md` ("Execute multi-item
work as an orchestrator") and the layout in `README.md`'s "Execution
section". Executors are `plan-executor` subagents: their brief, rules,
escalation triggers and report format live in
`.claude/agents/plan-executor.md` and aren't repeated here.
Plan-specific settings:

- **Orchestrator:** Claude Opus 5.5 in the main session.
  **Executors:** `plan-executor` on Sonnet 5.5, each in its own worktree
  (`isolation: "worktree"`) on branch `wip/<id>`.
- **Concurrency:** at most **4** agents at once (Decision log). The host
  has 8 GB of memory: `mypy` peaks at about 500 MB per run and the unit
  tests at about 200 MB, with about 3.9 GB free while the stack runs.
  Waves keep their structure; the orchestrator runs each wave's items in
  batches of 4, dependency-critical items first (e.g. Wave 1: D1, S1,
  O1, D2), and the bench lane still runs only with no agents active.
- **"Done when" for every brief:** `ruff check`, `ruff format --check`,
  `mypy --strict`, and the unit tests touching the write set all pass
  in the worktree.
- **Library docs:** context7 is authorized, for executors and the
  orchestrator alike.

### Serialized lanes (shared resources, never parallel)

- **Verification lane (orchestrator):** after each `wip/<id>` branch is
  merged into the integration branch, run the full
  `prek run --all-files --hook-stage manual`, including integration and
  e2e, one merge at a time. These suites share the devcontainer's
  Postgres, Redis, S3 and Keycloak, and e2e starts its own app process
  on a fixed port, so parallel runs would interfere with each other. A
  red result goes back to the owning agent as an escalation-style
  message.
- **Bench lane (one long-lived Sonnet agent, `L1`):** runs every
  Phase 0–5 measurement against images built from specific commits.
  Measurements run only in quiet windows, when the orchestrator has no
  other agents running builds or tests, because CPU contention from
  parallel agents would distort the numbers. Alternatively, they run
  through `perf.yml` on a pushed branch on a dedicated runner, after
  the standing push approval (pre-flight item 10). `L1` reports numbers; the orchestrator accepts or reverts
  each change.

### Pre-flight: what the user sets up before kickoff

Step-by-step version for the user to work through:
[`2026-10-packages-performance-observability-preflight.md`](2026-10-packages-performance-observability-preflight.md).

Everything here is either something only the user can do (org admin
rights, third-party web UIs, rebuilding the devcontainer) or a decision
that would otherwise stop execution midway. Once all of it is done,
execution needs only the remaining gates below.

**Accounts and org settings (user only):**

1. **PyPI and TestPyPI:** accounts with 2FA. Register a *pending
   trusted publisher* on both for `craftainer-tool-crud` and
   `craftainer-tool-observability`: owner `craftainer`, repos `tool-crud` /
   `tool-observability`, workflow `release.yml`, no environment. Pending
   publishers work before the repos and projects exist.
2. **Org-level secrets and variables** (they need `admin:org`, which the
   orchestrator's token doesn't have, so new repos inherit them):
   - secret `TEMPLATE_SYNC_TOKEN`, visible to all repos (`ADR-0018`);
   - variable `PYPI_PUBLISH` (A1) for `tool-*` repos;
   - variable `CI_RUNNER` if a dedicated perf runner exists.
3. **Org-wide GitHub Apps** set to "All repositories", so new repos are
   covered with no per-repo step: Renovate, and CodSpeed (plus a
   `CODSPEED_TOKEN` org secret if CodSpeed requires one for public
   repos).
4. **Rulesets:** org rulesets can't be enforced on the Free plan, so
   each new repo gets repo-level copies of `template-fastapi`'s two
   rulesets, applied by the orchestrator (item 10, Decision log
   2026-10-18).

**Template-base (user merges, or delegates below):**

5. Merge `craftainer/template-base#12` (devcontainer `Dockerfile` into
   `.devcontainer/`), then cut a base release.
6. Run this repo's template sync to that release, and do its one-time
   Dockerfile upgrade (item W0a below) in the sync PR.
7. **Rebuild the devcontainer** after that sync, because
   `.devcontainer/` changed. Only the user can trigger a rebuild, so it
   has to happen before kickoff, not mid-run.

**Local environment:**

8. **Permissions:** the repo's shared `.claude/settings.json` allows the
   routine commands, asks before release triggers and variable changes,
   and denies manual publishing, force or direct pushes to `main`,
   merging, and repo deletion (`.claude/README.md`). Nothing to set up
   per user.
9. **Resources:** the machine kept awake for the run. With 8 GB of
   memory, concurrency is capped at 4 (Execution). The GitHub CLI is
   logged in (`gh auth status`); it's part of the devcontainer via
   template-base, and its login persists across rebuilds. Start from a fresh session,
   so `plan-executor` is loaded and the orchestrator's context is clean.

**Decisions made in advance** (recorded in the Decision log):

10. **Standing approvals (granted 2026-10-17):** the orchestrator may,
    without asking:
    - create `craftainer/template-python-package`, `craftainer/tool-crud`
      and `craftainer/tool-observability`;
    - push branches and open PRs in those repos, in template-base, and
      here;
    - trigger template-base's `release.yml`;
    - copy `template-fastapi`'s rulesets onto the three new repos
      (Decision log 2026-10-18).

    The user approves and merges every PR. Nothing is published to
    PyPI or TestPyPI by hand: packages ship only through each repo's
    `release.yml` (trusted publishing inside the workflow), and
    triggering a `tool-*` release is a user gate.
11. **Bench-lane acceptance rule:** a change is kept if its median
    capacity over 3 runs beats the baseline median by more than the
    larger run-to-run spread and by at least 3%. Otherwise it's
    reverted. The same rule decides the Granian switch.
12. **Batching:** questions that don't block the current wave are
    collected and asked together at the end of the wave, not one at a
    time.

### Remaining gates (the orchestrator asks; nothing proceeds without a yes)

With pre-flight done and item 10 granted, only these remain. Gates of
the same kind that fall in one wave are batched into a single request:

| Gate | Before |
| --- | --- |
| G0 | Kickoff: confirm pre-flight items 1–9 are done. |
| G-pr | Merging any PR (user approves and merges): the template repo and package-repo scaffolding, template-base changes (B1), the package moves, and the integration branch into `main`. Each wave's PRs are raised together. |
| G-rel | Triggering `release.yml` in `tool-crud`/`tool-observability` (TestPyPI dry run first, then PyPI), and in `template-python-package`. |
| G-esc | Any escalation whose decision is really the user's: scope, security trade-offs, deleting anything outside this plan's own branches and repos. |
| G-final | Deleting this plan file and closing out (after X2/X3 have folded it into ADRs and docs). |

Anything not covered by item 10 or these gates (e.g. deleting a repo or
branch it didn't create, changing org settings) is asked for
individually.

### Waves

Each wave's items have disjoint write sets. The orchestrator merges
them in table order. A later wave starts only when everything it
depends on is merged and verified.

**Wave 0: serial foundation (after G0).** These touch nearly every
file, so they run alone and first. W0a lands in the template-sync PR
during pre-flight (items 5–7), before the devcontainer rebuild.

| ID | Item | Write set |
| --- | --- | --- |
| W0a | **One top-level Dockerfile** (decided; base side is `craftainer/template-base#12`). In the sync PR to the base release containing #12, do the one-time upgrade: rename `app.Dockerfile` → `Dockerfile` and `app.Dockerfile.dockerignore` → `.dockerignore`, overwriting base's old root files. Update every reference: `Makefile` (`-f app.Dockerfile`), the repo-root `compose.yml`, `scripts/check-dockerfile-versions.sh` (now compares `.devcontainer/Dockerfile` with `Dockerfile`) and its README, `docs/TEMPLATE.md`, `docs/architecture.md`, and this repo's sync manifest (`Dockerfile`/`.dockerignore` stay `replace` for template-fastapi's own instances; `app.Dockerfile*` entries go). Accepted ADRs keep their old wording. | those files |
| W0 | A4 rename in place (`crud` → `craftainer_tool_crud`, `health` → `craftainer_tool_observability.health`), and move `app/telemetry.py`'s logging (JSON formatter, redaction, OTLP log bridge) to `craftainer_tool_observability.logs`, with the service name taken from `OTEL_SERVICE_NAME` instead of `settings.app_name` (A3). Add every new dependency for the whole plan in one go (`pytest-benchmark`, `pytest-codspeed`, `py-spy`, `pyinstrument`, `opentelemetry-instrumentation-fastapi`/`-sqlalchemy` at `0.65b0`, `granian`, `squawk-cli`) plus `uv lock`. Add `--ignore=tests/bench` to pytest `addopts`. This means no later item edits `pyproject.toml` dependencies or `uv.lock`. | `src/`, `tests/`, `alembic/env.py`, `pyproject.toml`, `uv.lock`, living `README.md`s, `compose.yml`/`.devcontainer/compose.instance.yml` env (`OTEL_SERVICE_NAME`) |

**Wave 1: fan-out (17 agents, after W0 is verified; T1–T3 and B1 run
under the standing approvals).**

| ID | Item | Write set |
| --- | --- | --- |
| T1 | A1 template: scaffold (pyproject, `src/`, `tests/`, prek, import-linter, coverage gate) | template repo: those paths |
| T2 | A1 template: release `Makefile` + release-check script | template repo: `Makefile`, `scripts/release-check*` |
| T3 | A1 template: README, `docs/TEMPLATE.md` notes, ADR, Renovate, sync-manifest entries, CodSpeed workflow | template repo: docs, `.github/` |
| B1 | A2: `id-token: write` on template-base's publish job | template-base: `release.yml` |
| D1 | A3: decouple crud (settings and engine injection, move `xml_codec`/`web_components` in, rate-limit decorator injection, extras), plus independence contracts for crud and observability | `src/craftainer_tool_crud/`, `src/app/{main.py,crud_1/,xml_codec.py,web_components.py}`, moved tests, pyproject `[tool.importlinter]` only |
| P1 | Phase 0.1/0.4/0.5: `compose.perf.yml` (caps, `SYS_PTRACE`), docker-stats sampler, py-spy profile script | `compose.perf.yml`, `tests/perf/{stats,profile}.*` |
| P2 | Phase 0.2/0.3: Locust capacity mode (`LoadTestShape`), `--processes`, JSON summary | `tests/perf/locustfile.py`, `tests/perf/README.md` |
| P3 | Phase 0.6: app-level microbenchmarks (token verify, ASGI round trip) | `tests/bench/` |
| P5 | CI: capped stack + relative-baseline check in `perf.yml`, capacity job, CodSpeed workflow for this repo | `.github/workflows/{perf,codspeed}.yml`, `.github/workflows/README.md` |
| S1 | Phase 3/4 settings: `DB_POOL_*`, `POSTGRES_SSLMODE` + production guardrail, `DB_*_TIMEOUT`, `RUN_MIGRATIONS_ON_STARTUP` (fields, validation, tests only; no consumers yet) | `src/app/config.py`, its unit tests, `src/app/README.md` config section |
| R1 | Phase 1: `runner.sh` flags, `--limit-concurrency`, Phase 7.1 `--timeout-graceful-shutdown`, `APP_SERVER` switch (uvicorn/granian) + a lifespan check under Granian, `UV_COMPILE_BYTECODE` (code only; measured in the bench lane) | `runner.sh`, `Dockerfile` builder stage, `scripts/builder-sync-*.sh` |
| R2 | Phase 2: JWKS prefetch at startup + off-loop cache-miss path | `src/app/oidc.py`, its tests |
| O1 | Phase 5.2–5.4, 5.6, in the package's `[otel]` extra: tracer and meter providers, `instrument_app()` / `instrument_engine()` / pool-gauge helpers, trace-id log correlation, in-memory-exporter tests (not wired into `main.py`); Phase 7.4 scaling-metric docs; Phase 8.5 `service.version` from the release version + per-version query docs | `src/craftainer_tool_observability/{otel.py,logs.py}`, their tests, the package `README.md` telemetry section |
| D2 | A3 for observability: generic dependency checks (`PostgresCheck(engine)`, `RedisCheck(url)`, `S3Check(...)`, `HTTPCheck(url)` for OIDC discovery) into `health/checks/` behind extras; `app/health_checks.py` keeps only the registry wiring from `Settings` | `src/craftainer_tool_observability/health/checks/`, `src/app/health_checks.py`, their unit tests |
| N1 | A3b new package features: request-ID middleware, opt-in `/health/info`, opt-in profiling hook | `src/craftainer_tool_observability/{middleware.py,profiling.py,health/router.py}`, their tests |
| Q1 | Read-only audits, reported as two findings lists: (a) response path, `jsonable_encoder`, double validation in the crud router; (b) N+1 and `count()` patterns in repositories, and confirm slowapi's sync Redis call on the event loop | none (report only) |
| V1 | Phase 8.2–8.4: NFR-0027 (expand/contract), `migration-compat.yml` (N-1 check, skips until the first release with `RUN_MIGRATIONS_ON_STARTUP`), Squawk `prek` hook over rendered migration SQL | `docs/nfrs/NFR-0027-*.md`, `.github/workflows/migration-compat.yml`, `.github/workflows/README.md` (its section), `.pre-commit-config.yaml` (its hook), a new `scripts/lint-migrations.sh` |

Pre-assigned numbers, because ADRs and NFRs are numbered sequentially
and X1 and X2 (Wave 2) run in parallel:
- X1 gets ADR 0019 (perf CI and benchmarks), 0020 (package extraction,
  including the observability package's scope) and 0021 (OTel), plus NFR-0025 (observability scope).
- X2 gets ADR 0022 (pool modes), ADR 0023 (caching) and NFR-0026
  (pooling).
- V1 (Wave 1) gets NFR-0027 (expand/contract migrations).
- ADR 0024 is reserved for the server choice, written in Wave 4 only
  if Granian wins.

Shared living docs (`src/app/README.md`, `.github/workflows/README.md`)
may be edited by more than one item, but only in separate sections. The
orchestrator resolves any merge overlap.

`L1` starts in parallel with Wave 1: it measures the baseline on an
image built from `main` before Wave 0, using P1/P2's harness once
those are merged (Phase 0.7).

**Wave 2: integration (10 agents, after D1, D2, S1 and O1 are merged).**

| ID | Item | Write set |
| --- | --- | --- |
| E1 | Phase 3.1 + Phase 4: `app/db.py` engine factory (all three pool modes, SSL, timeouts, pre-ping), unit tests + an integration test for `local` | `src/app/db.py`, its tests |
| M1 | `main.py` wiring: `app.db` engine (interface fixed in E1's brief), `RUN_MIGRATIONS_ON_STARTUP`, `gc.freeze()`, `instrument_app`/`instrument_engine`, N1's request-ID middleware, docs routes off in production, Phase 7.2 `engine.dispose()` on lifespan shutdown | `src/app/main.py`, its tests |
| H1 | Phase 7.3: SSE stream vs `SIGTERM` integration test (uvicorn subprocess, exit within timeout, lossless `Last-Event-ID` resume). Report-only if it fails; no code change without escalation. | a new `tests/integration/test_graceful_shutdown.py` |
| F1 | Phase 2 fixes from Q1(a) | `src/craftainer_tool_crud/controllers/{crud_router,crud_actions}.py` |
| C2 | Phase 6.2: cache protocol + optional cache param on the stats/predict routes; `app.cache` (Redis, event-driven invalidation, TTL). Keys include the app version (Phase 8.6). `main.py` wiring goes through M1, with the interface fixed in both briefs. | `src/craftainer_tool_crud/controllers/crud_stats.py`, a new `src/craftainer_tool_crud/interfaces/cache.py`, `src/app/cache.py`, their tests |
| F2 | Phase 2 fixes from Q1(b) (repositories) | `src/craftainer_tool_crud/repositories/` |
| F3 | Async rate-limit storage, only if Q1(b) confirmed the blocking call | `src/app/rate_limit.py`, its tests |
| X1 | ADR drafts: perf CI and benchmarks (amends 0010), package extraction, OTel + NFR superseding 0023 | `docs/adrs/`, `docs/nfrs/` (new files only) |
| X2 | ADR + NFR superseding 0016 for `DB_POOL_MODE`, and the Phase 6 caching ADR, with measured numbers left as `TBD` | `docs/adrs/`, `docs/nfrs/` (new files only) |
| L1 | A/B runs, one at a time: each R1 flag, bytecode (startup time), `--limit-concurrency` under overload, uvicorn vs Granian, R2, F1–F3, `null` vs `local` | none (report only) |

**Wave 2b (1 agent, after F1 is merged, because it shares
`crud_router.py`).**

| ID | Item | Write set |
| --- | --- | --- |
| C1 | Phase 6.1: `ETag`/`304`/`If-Match`/`412` on JSON, XML and web routes, plus a revalidating Locust task | `src/craftainer_tool_crud/controllers/crud_router.py`, its tests, `tests/perf/locustfile.py` |
| L1 | A/B: C1 revalidation, C2 stats cache hit/miss | none (report only) |

**Wave 3: packages (after T1–T3, B1 synced, D1/D2/N1/O1/F1/F2/C1/C2 merged, and
pre-flight item 1).**

| ID | Item | Write set |
| --- | --- | --- |
| K1 | A5 for `tool-crud`: `git filter-repo` history, move code and tests, Postgres via `compose.instance.yml`, `0.1.0` (PR merged by the user, then released via `release.yml` after G-rel) | `tool-crud` repo |
| K2 | A5 for `tool-observability` | `tool-observability` repo |
| L1 | Phase 5.7 OTel overhead (unset / 100% / 10% sampling); `gc` variants | none (report only) |

**Wave 4: switch and close (serial, after both `0.1.0` releases are on PyPI).**

| ID | Item | Write set |
| --- | --- | --- |
| A6 | Switch this repo to the published `0.1.0` pins; delete `src/craftainer_tool_*` and the moved tests | `pyproject.toml`, `uv.lock`, `src/`, `tests/` |
| L1 | Final capacity run versus the baseline; Phase 7.6 shutdown-under-load run | none (report only) |
| X3 | Fold Phase 4's environment-variable table, Phase 7's and Phase 8's deployment notes, and the Phase 8 migration rules into a "Kubernetes deployment (future)" section of `docs/architecture.md`, so they outlive this plan | `docs/architecture.md` |
| X2 | Fill in the `TBD` numbers in the ADRs/NFRs from `L1`'s reports | its ADR/NFR files |

Then the orchestrator runs the verification lane one last time and,
per `docs/plans/README.md`, folds this plan into the ADRs written above
and deletes it after G-final. The orchestrator pushes the integration branch and opens its PR into `main`; the user merges it (G-pr).

## Approach

### Part A: Python package template, then extract `crud` and observability

Today `crud` and `health` are generic, but they ship only inside this
repo's image (`pyproject.toml`'s hatch `packages`). Publishing them lets
other apps reuse them, and lets each have its own release cycle, tests
and benchmarks. `health` alone would be a very small package, so it
grows into **`craftainer-tool-observability`**: everything a service
needs to be operable, in one package with optional extras.

| Module | Contents | Extra |
| --- | --- | --- |
| `health` | Today's `src/health/` (registry, router, `/health/live`, `/health/ready`) | core (FastAPI only) |
| `health.checks` | Generic dependency checks taking an engine, URL or client, moved from `app/health_checks.py` | `[sqlalchemy]`, `[redis]`, `[s3]`, `[http]` |
| `logs` | JSON formatter, credential redaction, optional OTLP log bridge, moved from `app/telemetry.py` | core; OTLP part in `[otel]` |
| `otel` | Phase 5: tracer and meter providers, `instrument_app()`, `instrument_engine()`, pool gauges, trace-id log correlation | `[otel]` (+ `[sqlalchemy]` for the engine parts) |
| `middleware` | Request-ID middleware (pure ASGI): read or create `X-Request-ID`, validate it (length and charset, so it can't inject into logs), echo it, and attach it to log lines and the active span | core |
| `health` (opt-in) | `/health/info`: app version and commit from env/package metadata. Off by default, because it discloses the version. | core |
| `profiling` | Opt-in pyinstrument hook. Off unless an env variable enables it, and refused under `MODE=production`. | `[profiling]` |

Not in the package: RFC 9457 problem details (API errors, not
observability), a Prometheus `/metrics` endpoint (Decision log), and a
"readiness drain" on shutdown. Kubernetes already removes terminating
pods from Service endpoints, and Phase 7's `preStop` sleep covers the
propagation delay.

**A1. New template repo: `craftainer/template-python-package`.** An
instance of `craftainer/template-base` (`ADR-0018`), the same way
`template-fastapi`, `template-react` and `template-axum` are. Like
`template-fastapi`, it is itself a template, so `crud`, observability and
future libraries are created from it and receive fixes through template
sync. Contents:

- Created from a base release that includes `template-base#12`, so the
  only Dockerfile is `.devcontainer/Dockerfile`. A pure library ships
  no runtime image, so there's no top-level `Dockerfile`.
- `src/<import_name>/` layout with a `py.typed` marker, hatchling
  build, and `uv`.
- This repo's quality bar, copied:
  - strict `ruff` + `mypy --strict` config;
  - `pytest` with a 100% coverage gate;
  - `import-linter` for internal layering;
  - `pip-audit`;
  - all of it under `prek`.
- A `Makefile` implementing template-base's release contract
  (`docs/TEMPLATE.md`, "Release: a Makefile contract"):

  | Target | Package implementation |
  | --- | --- |
  | `release-arches` | `["amd64"]`: a pure-Python wheel is built once |
  | `build` | `uv build` → sdist and wheel in `dist/` |
  | `sbom` | Syft over the built wheel (same pinned Syft as this repo's `Makefile`) → SPDX JSON in `dist/` |
  | `release-assets` | Assert that the sdist, wheel and SBOM exist |
  | `publish` | `uv publish --trusted-publishing always`. Skipped with a message when the `PYPI_PUBLISH` repo variable isn't set, mirroring this repo's `OCI_REGISTRY` skip. |
  | `release-check` | Install the built wheel into a fresh venv and import it. If PyPI publishing is on, also `pip install` the published version from PyPI. |
  | `finalize` | No-op |

- Publishing uses PyPI **trusted publishing** (GitHub OIDC, no stored
  token). Each package registers a PyPI "pending publisher" (repo +
  `release.yml`) before its first release, and the first release goes
  to TestPyPI as a dry run.
- An optional CodSpeed benchmark workflow (see "CI" below), so each
  package benchmarks its own hot paths in its own repo.
- GPL-3.0 license (decided), matching this repo, so `release.yml`'s
  SBOM and the package metadata carry the same license as the apps
  using them.
- Renovate config, an ADR recording the template, and `docs/TEMPLATE.md`
  extension notes (e.g. how a package adds backing services through
  template-base's `compose.instance.yml` hook).

**A2. One template-base change.** Its `release.yml` (`replace` tier, so
only base can change it) grants only `contents: write`, and trusted
publishing needs `id-token: write`. Add that to the per-arch job that
runs `make publish`, PR it into template-base, and let it reach the
package template and this repo through the normal sync. For repos that
don't publish to PyPI, the grant is unused.

**A3. Decouple `crud` and observability from `app`, in place.**
`health` already imports only FastAPI and the stdlib. The observability
modules moving out of `app` need these changes:

| Today | Change |
| --- | --- |
| `app/telemetry.py` reads `settings.app_name` for the OTel resource | Use OTel's standard `OTEL_SERVICE_NAME` (set in compose and deployment env), so the module has no settings dependency at all (W0). |
| `app/health_checks.py`: Postgres/Redis/S3/OIDC check classes read `Settings` and import `crud`'s engine | The check classes take an engine, URL or client as constructor arguments and move into `health.checks` (D2). `app/health_checks.py` keeps only building the registry from `Settings`, including the `MODE=mock` fakes. |

`crud` imports five things back from `app`:

| `crud` imports | Change |
| --- | --- |
| `app.config.get_settings`: `database_url` (engine), `mode` (mock repository switch), `mqtt_*` (event sink), `bulk_action_max_matched`, `rate_limit_bulk_action`, `sse_keepalive_seconds` | `crud` stops reading settings. `app` creates the engine and session factory and passes them in, together with a small `crud`-owned config object (limits, SSE keepalive, MQTT connection details, and which repository to use), built from `app`'s `Settings`. |
| `app.xml_codec` | Moves into `crud`. Only `crud`'s router factories use it. |
| `app.web_components` | Moves into `crud`, same reason. |
| `app.rate_limit.limiter` | Stays in `app` (it holds the Redis-backed `slowapi` limiter). The router factories take an optional rate-limit decorator instead, so `crud` doesn't depend on `slowapi`. |

- Optional dependencies become extras: `craftainer-tool-crud[mqtt]`
  (`aiomqtt`) and `[xml]` (`defusedxml`).
- Migrations stay app-owned. `crud.models.revision`'s table is
  registered on the shared `Base.metadata` that `app`'s Alembic
  autogenerates against, as today. `crud`'s README must state that a
  release changing its models needs a new app-side migration
  (`NFR-0019`).
- Add an `import-linter` independence contract: `crud` and
  observability must never import `app`, and observability never
  imports `crud`. It's enforced here before the move, and
  becomes impossible to break after it.
- Unit tests of `crud`/observability, and `test_xml_codec.py` /
  `test_web_components.py`, move alongside the code in A5. The e2e
  suite, and `tests/integration/test_health_checks.py` against the real
  backing services, stay here as the integration tests of the published
  packages, so the observability repo needs no backing services of its
  own.

**A4. Names (decided).**

| | crud | observability |
| --- | --- | --- |
| GitHub repo | `craftainer/tool-crud` | `craftainer/tool-observability` |
| PyPI distribution | `craftainer-tool-crud` | `craftainer-tool-observability` |
| Import package | `craftainer_tool_crud` | `craftainer_tool_observability` |

All of these were free on 2026-10-17. The bare names (`crud`, `health`,
`fastapi-crud`, `fastapi-health`) are taken on PyPI. A published
library also shouldn't claim a generic top-level import name that
another installed package could shadow. `tool-*` is the org's repo
prefix for reusable libraries, next to `template-*`. In this repo the
rename is mechanical: imports, `import-linter` `root_packages`,
coverage `source`, `alembic/env.py`, the hatch `packages` list, and the
living `README.md`s. Accepted ADRs stay as written, because they're
historical records. Wave 0 below does the rename first, so every later
change is written against the final names. Paths elsewhere in this plan
use the pre-rename names (`src/crud/...`).

**A5. Create the package repos and move the code.**
`craftainer/tool-crud` and `craftainer/tool-observability` are created from
`template-python-package`. Use `git filter-repo` limited to each
package's paths to keep their history. `crud`'s repo adds Postgres
through `compose.instance.yml`, for its integration tests. Apply the
copied rulesets once the history import is on `main`, before any other
PR merges (Decision log 2026-10-18). Release
`0.1.0` of each: TestPyPI first, then PyPI. Version as SemVer, staying
in `0.x` until the public API settles.

**A6. Switch this repo to the packages.**
- Depend on `craftainer-tool-crud[mqtt,xml]==0.1.0` and
  `craftainer-tool-observability[otel,sqlalchemy,redis,s3,http]==0.1.0`.
  Renovate's PyPI manager bumps the pins
  from then on.
- Delete `src/craftainer_tool_crud`, `src/craftainer_tool_observability`
  and their moved tests, and drop them from hatch `packages`, coverage
  and the `crud`/observability
  `import-linter` contracts (those contracts now live in the package
  repos).
- `src/` is synced to this template's instances, so they receive the
  deletion and the new pins in their next sync PR. Say so in the
  release notes.
- For editing a package and the app together, document a local-only
  `uv` path override (`[tool.uv.sources]` editable path), never
  committed.
- Run the full check suite plus the Phase 0 perf baseline: no runtime
  change expected.

### Phase 0: measure before changing anything

1. **Make load numbers reproducible.** Add a perf-only compose override
   (`compose.perf.yml`, layered on the repo-root `compose.yml`) that
   caps `api` at `cpus: "1"` and `mem_limit: 2g`, matching the
   challenge box. This is the reference budget that all capacity numbers
   in this plan refer to. That way the app is the bottleneck, and
   numbers compare across machines and runners. Backing services stay
   uncapped so they don't become the limit.
2. **Add a capacity mode to `tests/perf/locustfile.py`**, alongside the
   existing fixed-20-user `NFR-0024` check. A Locust `LoadTestShape`
   steps users up (hold each step N minutes, discard a warm-up window)
   and records the highest step whose p95, p99 and error rate stay
   within `NFR-0024`'s ceilings. That number is the headline metric,
   the same way the video measured capacity. The fixed check still
   answers "did we regress?", and capacity answers "how far can we go?".
3. **Make sure the load generator isn't the bottleneck.** The video's
   own k6 machine ran out of RAM first. Run Locust with
   `--processes -1` (one worker per core), watch its CPU warning, and
   report generator CPU next to results.
4. **Record more than latency.** Each run stores p50/p95/p99, RPS,
   error rate, and `api` container CPU and RSS (sampled with
   `docker stats --no-stream` during the hold), in one JSON summary
   beside Locust's CSV/HTML.
5. **Profile under load.** Add `py-spy` to the `dev` group and attach it
   to the uvicorn PID during a capacity run:
   `py-spy record --pid <pid> --format speedscope --duration 60`. It
   attaches from outside, so no app changes are needed, but the
   container needs `SYS_PTRACE`, granted only in `compose.perf.yml`.
   Use `pyinstrument` ad hoc for single-request call trees. Phases 1–3
   are ordered by expected value, but the flame graph decides the real
   order.
6. **Benchmark the hot paths offline.** Add `pytest-benchmark` cases
   that run without network or DB: `decode_bearer_token` with a
   pre-loaded key, view serialization (`model_dump_json`), and
   `xml_codec` encoding. Add one in-process ASGI benchmark (`httpx`
   `ASGITransport`, `MODE=mock`) that isolates framework and app
   overhead from Postgres. These live under `tests/bench/`, a fifth
   suite that the default `pytest` run doesn't collect. Collecting it
   would distort the 100% coverage gate and slow every run.
7. **Establish the baseline.** Run capacity mode at least 3 times on
   the current `main` and record the median and spread. Every later
   change is one variable at a time, A/B against that baseline. A
   change counts only if it improves the median by more than the
   spread.

### Phase 1: configuration only (no code paths change)

Each item is one A/B run:

- `runner.sh`: add explicit `--loop uvloop --http httptools`,
  `--no-access-log` (if `ADR-0007`'s structured logging doesn't depend
  on uvicorn's access log; check first), `--no-proxy-headers` unless a
  proxy is in front, a higher `--backlog`, and a
  `--timeout-keep-alive` longer than the clients' idle gap.
- Disable `/docs`, `/redoc` and `/openapi.json` under `MODE=production`
  if nothing consumes them. This is mostly hardening; the throughput
  effect is minimal.
- Workers: `runner.sh` starts one process. On hosts with more than one
  core, `--workers N` (N = cores) is the largest single lever. The
  rate limiter is already Redis-backed, so it's multi-worker safe. On
  the 1-CPU budget, measure that 1 worker beats 2.
- Log level: confirm `MODE=production` doesn't emit per-request
  INFO/DEBUG records through the JSON formatter.
- **Precompile bytecode:** set `UV_COMPILE_BYTECODE=1` in
  `Dockerfile`'s builder stage (named `app.Dockerfile` until W0a).
  Today neither
  `scripts/builder-sync-*.sh` compiles, and the runner sets
  `PYTHONDONTWRITEBYTECODE=1`, so every container start recompiles
  every imported module (FastAPI, Pydantic, SQLAlchemy, boto3, OTel).
  This affects startup, not throughput: deploys, autoscaling, and pod
  restarts after a DB failover. Add time-to-`/health/ready` from
  container start to the Phase 0 metrics, and A/B it.
- **Load shedding:** expose uvicorn's `--limit-concurrency` through
  `runner.sh` (env-driven, unset by default). Size it from the capacity
  number, so overload fails fast with 503s instead of falling off the
  latency cliff the video saw in every entry. Uvicorn sends its own
  plain 503 before the app runs, so this response can't be RFC 9457
  problem details. Document that rather than adding middleware.
- **Server A/B, Granian:** `runner.sh` picks the server from an
  `APP_SERVER` variable (`uvicorn` default, `granian`). Granian is an
  ASGI server with its HTTP layer in Rust (BSD-3-Clause, in production
  use, with built-in backpressure, worker RSS limits, and access log
  off by default). Its own benchmarks show large wins on bare
  endpoints, while independent ones are mixed and shrink once a
  database is involved. Before measuring, verify that lifespan runs
  under `--interface asgi`, since startup migrations depend on it.
  Switch the default only if it wins capacity at the reference budget,
  and record that in its own ADR.
- **Not now (decided):** Python 3.14's JIT (experimental, −10% to +20%
  depending on workload), the free-threaded build (disables the JIT,
  compatibility risk for asyncpg and uvloop, no gain at 1 vCPU), and
  gzip in the app (it costs CPU on the single core; the ingress should
  compress).

### Phase 2: code changes inside the framework's own APIs

- **Response path:** check that every JSON CRUD route returns a typed
  view (return annotation or `response_model`), so FastAPI serializes
  in Pydantic's Rust core, and that no hot route returns a plain
  `dict` or goes through `jsonable_encoder`. Avoid double validation
  (constructing a view and then having FastAPI validate it again
  against the same model).
- **GC:** after lifespan startup, `gc.collect(); gc.freeze()`, and
  measure `gc.set_threshold(...)` variants. Reject if RSS grows without
  a latency win.
- **Blocking calls on the event loop** (find with py-spy):
  - `_get_jwks_client().get_signing_key_from_jwt(...)` runs synchronous
    PyJWT code inside the async `get_current_claims`. On a JWKS cache
    hit this is CPU only. On a cache miss (key rotation) it performs
    blocking HTTP on the event loop and stalls every in-flight request.
    Prefetch the JWKS at startup, and run the miss path through
    `run_in_threadpool`.
  - slowapi's `limiter.limit(...)` is backed by the synchronous `limits`
    Redis storage, so each rate-limited update/delete does a blocking
    Redis round trip on the event loop. If the flame graph confirms it,
    switch to `limits`' async Redis storage (its own documented API) or
    move the check off-loop.
- **RS256 verification cost:** don't cache verified tokens, and don't
  hand-roll a verifier. PyJWT's `jwt.decode` with RS256 (2048-bit key,
  audience and issuer checks) measured about 48 µs per call in the
  devcontainer. At the reference budget that's under 5% of one CPU at
  1,000 req/s, which is small next to a Postgres round trip. A
  verified-claims cache would save at most that, while adding stale
  trust after key rotation or a role change, and cache-key pitfalls:
  different encodings of the same token produce different string keys.
  Revisit only if the flame graph shows verification above about 10%
  of CPU.
- **Query shape:** check the generic repository for N+1 queries and
  `count()` calls that run alongside every list. Any fix must stay
  generic (`NFR-0004`).

### Phase 3: connection modes, switchable by setting (needs an ADR)

`NullPool` costs a TCP handshake, Postgres auth, backend fork and
statement re-preparation on every request. That is exactly the cost the
challenge's fastest entries avoided by reusing one connection.
`NFR-0016` already names the sanctioned fix, an external pooler, and
`ADR-0010` built the perf suite partly to measure this trade-off.

The right pooling choice depends on where the app is deployed, not on
the code, so make it deployment configuration. Add one setting,
`DB_POOL_MODE` (`Settings.db_pool_mode`, set from the environment per
`NFR-0017`), which `crud/models/base.py` reads when it builds the
engine:

| `DB_POOL_MODE` | Engine | Use when |
| --- | --- | --- |
| `null` (default) | `NullPool`, as today | Tests, `dev`, `mock`. Behavior stays the same until a deployment opts in. |
| `local` | `AsyncAdaptedQueuePool` with `DB_POOL_SIZE`, `DB_MAX_OVERFLOW`, `DB_POOL_RECYCLE`, `pool_pre_ping=True` | The app connects straight to Postgres (repo-root `compose.yml`, or a CloudNativePG `<cluster>-rw` service) and the connection budget below fits |
| `external` | `NullPool` + `connect_args={"prepared_statement_name_func": lambda: f"__asyncpg_{uuid4()}__"}` | Behind PgBouncer in transaction mode, e.g. a CloudNativePG `Pooler`. This is SQLAlchemy's documented asyncpg-behind-PgBouncer recipe: asyncpg's default numbered statement names collide across clients that share a server connection. |

**Choosing `local` vs `external` (connection budget):** replicas ×
workers × (`DB_POOL_SIZE` + `DB_MAX_OVERFLOW`) must stay below
Postgres's `max_connections`, minus reserved slots and headroom for
migrations and admin sessions. While it fits, use `local`: it's one
fewer network hop, and no extra process takes CPU. On the 1-vCPU
budget, PgBouncer would compete with the app for the same core, the
same reason the challenge's fastest entries dropped Nginx. Switch to
`external` once replica autoscaling pushes the total past that limit,
which is the problem PgBouncer exists to solve.

1. Add the setting and an engine factory. Unit-test that each mode
   produces the right pool class and `connect_args`. Integration-test
   `local` against the devcontainer's Postgres inside one event loop.
2. Measure `null` vs `local` in capacity mode at the reference budget
   to size the win. The repo-root `compose.yml` sets
   `DB_POOL_MODE=local`, so `perf.yml` measures the mode a direct
   deployment would use.
3. `external` is covered only by step 1's unit tests. No PgBouncer
   service is added to any stack in this repo. Live-test it on the
   first deployment that actually sits behind a pooler: run PgBouncer in
   transaction mode with an explicit non-zero `max_prepared_statements`
   (the default changed across versions), and check that prepared
   statements don't pile up on server connections.
4. Write an ADR and an NFR superseding `NFR-0016`: pooling becomes
   per-deployment configuration, `NullPool` stays the default and test
   mode, and the ADR records the budget formula and step 2's numbers.

### Phase 4: environment variables ready for an HA Postgres operator

Scope: only settings the app reads from its environment (`NFR-0017`),
so a later deployment behind an operator is pure configuration.
Nothing operator-related goes into the devcontainer, `compose.yml`, CI
or Kubernetes manifests. CloudNativePG (CNPG) is the operator kept in
mind. Zalando, Crunchy PGO, Percona and StackGres expose the same
shape: a service pointing at the primary, an optional PgBouncer, and a
credentials secret. None of the variables below is CNPG-specific.

Every new variable defaults to today's behavior, so nothing changes
for the devcontainer or existing deployments:

| Variable | Default | Purpose | Later, under CNPG |
| --- | --- | --- | --- |
| `POSTGRES_HOST` / `_PORT` / `_USER` / `_PASSWORD` / `_DB` | as today | Already exist | From the `<cluster>-app` secret via `secretKeyRef`. Host is `<cluster>-rw`, or the `Pooler`'s service name. Check the secret's key names with `kubectl` then. |
| `DB_POOL_MODE` | `null` | Phase 3 | `local` against `<cluster>-rw`, `external` behind a CNPG `Pooler` (PgBouncer, transaction mode) |
| `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` / `DB_POOL_RECYCLE` | SQLAlchemy defaults | `local`-mode pool sizing | Sized against the connection budget in Phase 3 |
| `POSTGRES_SSLMODE` | unset (no TLS, as today) | Passed through to asyncpg's `ssl` | `require` or `verify-full` (CNPG manages server certificates). Add a production guardrail requiring it, matching the existing OIDC, S3, Redis and MQTT TLS guardrails in `config.py`. |
| `DB_CONNECT_TIMEOUT` / `DB_COMMAND_TIMEOUT` | asyncpg defaults | asyncpg `timeout` / `command_timeout` | Short values, so requests fail fast during a failover (CNPG drops the old primary's connections; node-failure detection takes about 40–55s by default) instead of hanging |
| `RUN_MIGRATIONS_ON_STARTUP` | `true` | Lets `app.main`'s lifespan skip `alembic upgrade head` | `false` once several replicas would race, or when connecting through PgBouncer. Migrations then run from a separate step against `<cluster>-rw` directly. That step belongs to the future deployment, not this repo. |

Each variable gets a unit test of its parsing and its effect on the
engine or lifespan, plus a row in `src/app/README.md`'s configuration
docs.

**Not in scope now; notes for when deployment happens:** map
lost-connection errors to 503 + `Retry-After` and never auto-retry
writes. Confirm `/health/live` doesn't touch the database
(`NFR-0008`), so a database failover doesn't restart app pods. Keep all
traffic on `-rw`, not `-ro` replicas, because the CRUD layer assumes it
reads its own writes and replication lag would break that.

### Phase 5: optional OpenTelemetry metrics and traces (needs an ADR)

Today only logs are exported over OTLP, and only when
`OTEL_EXPORTER_OTLP_ENDPOINT` is set (`ADR-0007`, `NFR-0023`). Extend
that to all three signals with the same switch, and with no
behavior change when it's unset.

1. **Decision records:** a new ADR superseding `ADR-0007`'s
   "logs only" decision, and an NFR superseding `NFR-0023`. Keep
   `ADR-0007`'s other rule: OTel's own standard environment variables
   are the only configuration, never re-modeled on `Settings`. That
   gives per-signal on/off with `OTEL_TRACES_EXPORTER` /
   `OTEL_METRICS_EXPORTER` / `OTEL_LOGS_EXPORTER` (`otlp` or `none`),
   sampling with `OTEL_TRACES_SAMPLER` (+ `_ARG`), the export interval
   with `OTEL_METRIC_EXPORT_INTERVAL`, a full kill switch with
   `OTEL_SDK_DISABLED`, and excluded routes with
   `OTEL_PYTHON_FASTAPI_EXCLUDED_URLS` (exclude `/health/.*`, so probes
   don't flood traces).
2. **Wiring in `craftainer_tool_observability.otel`** (`[otel]` extra;
   `app.main` only calls it): next to the existing
   `LoggerProvider`, set up a `TracerProvider` (batch span processor,
   OTLP/HTTP span exporter) and a `MeterProvider`
   (`PeriodicExportingMetricReader`, OTLP/HTTP metric exporter). Both
   exporters ship in `opentelemetry-exporter-otlp-proto-http`, which is
   already a dependency. All three share one `Resource`
   (`service.name`, plus `service.version` and
   `deployment.environment` from `OTEL_RESOURCE_ATTRIBUTES`).
3. **Instrumentation, using OTel's packages only:**
   - `opentelemetry-instrumentation-fastapi`: server spans and HTTP
     request-duration histograms per route.
   - `opentelemetry-instrumentation-sqlalchemy`, attached to
     `engine.sync_engine`: query spans, and connection-pool metrics if
     the package emits them. Otherwise add a few observable gauges
     reading `engine.pool.status()` (checked out, overflow), which is
     how the Phase 3 pooling change gets verified in production.
   - Pin instrumentation versions to the existing
     `opentelemetry-instrumentation-logging` release line.
4. **Log/trace correlation:** add `trace_id` / `span_id` to every
   JSON log line (`craftainer_tool_observability.logs`) when a span is active, so a slow trace can be
   found from its logs and the other way round.
5. **No `/metrics` endpoint.** Metrics are pushed over OTLP. In
   Kubernetes they go to an OTel Collector, or straight to Prometheus
   3's OTLP receiver (`--web.enable-otlp-receiver`, HTTP only, served at
   `/api/v1/otlp/v1/metrics`). This avoids the scraped endpoint's
   multi-worker problem (`prometheus_client` multiprocess mode), and
   OTel's Python docs recommend OTLP push for forking servers.
   Kubernetes deployments run one worker per pod anyway, and scale by
   adding pods. Add a scrape endpoint only if the eventual cluster has
   neither a collector nor an OTLP receiver.
6. **Tests:** unit tests use OTel's in-memory span and metric
   exporters to assert that spans exist for a request and a query, that
   health routes are excluded, and that log lines carry the trace ID. No
   collector is added to the devcontainer or `compose.yml`.
7. **Overhead budget:** with the Phase 0 harness at the 1 vCPU / 2 GB
   budget, run capacity mode three ways: telemetry unset, enabled with
   sampling at 100%, and enabled with sampling at 10%. Record the cost
   in the ADR, and pick a default sampling recommendation from it.
   Telemetry that eats the capacity it's meant to watch is a
   regression too.

### Phase 6: caching (needs an ADR)

Rule: share cached data across users only when it isn't per-user.
Heroes are owner-scoped (`ADR-0011`), so a shared cache of lists or
records would need the user and their roles in every key, and one
mistake there leaks data. On 1 vCPU, a Redis round trip also costs
about as much as the indexed query it would replace.

1. **Conditional GETs (`ETag` / `304`), in the crud router:**
   - Single-record GETs get an `ETag` derived from the record's id and
     `updated_at` (or its latest revision).
   - List GETs get a weak `ETag` over the ids and `updated_at` values of
     the page.
   - Honor `If-None-Match` with a `304` and no body, and send
     `Cache-Control: private, no-cache`: browsers may revalidate, shared
     proxies never store.
   - The same `ETag`s enable `If-Match` on `PATCH`/`DELETE` (`412` on
     mismatch): optimistic concurrency control, so concurrent edits
     can't silently overwrite each other.
   - Keep JSON, XML and web parity (`ADR-0005`, `ADR-0017`).
   - Measure the saving in the bench lane with a Locust task that
     revalidates. The query still runs, so the saving is serialization
     and bandwidth.
2. **Server-side cache for `/stats` and `/predict`:**
   - Whole-table aggregates are the most expensive reads, and they
     aren't per-record.
   - `crud` defines a small cache protocol, and the router factories
     take an optional cache. `crud` itself never depends on Redis.
   - `app.cache` implements the protocol with `redis.asyncio`, which is
     already a dependency.
   - Keys include the resource, query parameters, and the caller's
     role/ownership scope.
   - Invalidate on writes through the CRUD event stream the app already
     publishes (`ADR-0015`), with a short TTL as the safety net.
   - Off unless `STATS_CACHE_TTL_SECONDS` is set.
   - Before writing a helper, check that `fastapi-cache2` is still
     maintained and fits.
3. **Already covered elsewhere:** the JWKS and settings caches,
   SQLAlchemy's compiled-statement cache, and asyncpg's
   prepared-statement reuse (Phase 3).

### Phase 7: autoscaling readiness

Same scope as Phase 4: app-side changes and environment variables
only, with no manifests, operators or autoscalers in this repo. The goal
is that HPA, KEDA, VPA and a node autoscaler (Karpenter or Cluster
Autoscaler) can drive this app later through configuration alone.

**Already in place, or covered by other phases:**

- **Stateless pods.** Rate limiting and the Phase 6 stats cache are in
  Redis, auth is stateless JWT, files are in S3, and the JWKS cache is
  per pod by design.
- **Signal handling.** `runner.sh` `exec`s uvicorn under an exec-form
  `ENTRYPOINT`, so the server is PID 1, receives `SIGTERM`, stops
  accepting connections, and finishes the requests in flight.
- **Startup.** Phase 1 precompiles bytecode, Phase 4 can move migrations
  out of startup, and Phase 0 measures time-to-ready.
- **Per-pod capacity.** The 1 vCPU / 2 GB reference budget is also the
  pod size, so Phase 0's capacity number is exactly what a scaling
  target is derived from.
- **Scaling metrics.** Phase 5's FastAPI instrumentation emits the
  standard `http.server.active_requests` and
  `http.server.request.duration`.

**App-side work:**

1. **Shutdown timeout:** `runner.sh` passes
   `--timeout-graceful-shutdown` from `GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS`
   (unset by default, which keeps uvicorn's behavior). This bounds how
   long a scale-down waits for open connections.
2. **Lifespan shutdown:** today `app.main`'s lifespan does nothing
   after `yield`. Dispose the engine there (`await engine.dispose()`),
   so `local`-mode pool connections close cleanly instead of being cut
   when the process exits.
3. **SSE streams on scale-down:** `/events` streams never end on their
   own, so they hold a terminating pod open until the shutdown timeout
   cancels them. That's acceptable only if clients resume losslessly
   elsewhere. The router already resumes from `Last-Event-ID` through
   the broker's persistent MQTT session. Add an integration test: open
   an SSE stream against a uvicorn subprocess, send `SIGTERM`, and
   assert that the process exits within the timeout plus a margin, and
   that a reconnect with the last event id loses no events. Add code (a
   router-factory shutdown hook) only if that test fails, and escalate
   first (trigger 4): it means hooking into the server's shutdown.
4. **Scaling-metric docs:** document that deployments set
   `OTEL_RESOURCE_ATTRIBUTES=k8s.pod.name=$(POD_NAME)` (Downward API),
   so metrics can be split per pod. Include an example PromQL for KEDA's
   Prometheus scaler: average in-flight requests per pod, from
   `http_server_active_requests` after Prometheus's OTLP name
   translation. Target about 60–70% of the measured per-pod capacity.
5. **Connection budget vs replicas:** Phase 3's formula sets the upper
   bound on the autoscaler's `maxReplicas` (pods × workers ×
   (`DB_POOL_SIZE` + `DB_MAX_OVERFLOW`) < `max_connections` − reserve).
   Above that bound, use `DB_POOL_MODE=external`.
6. **Shutdown under load (bench lane):** run sustained load against one
   instance, send `SIGTERM` mid-run, and assert that every request
   accepted before the signal completes without a 5xx. New connections
   being refused is expected. A multi-replica rolling-restart test needs
   a load balancer and belongs to the eventual deployment, not this
   repo.

**Deployment notes for later (not implemented here):**

| Concern | Setting |
| --- | --- |
| Pod autoscaling | KEDA `ScaledObject` with the Prometheus scaler on in-flight requests per pod, or plain HPA on CPU as the simpler start. `minReplicaCount` ≥ 2. |
| Scale to zero | No. Every first request would wait for a cold start, KEDA's HTTP add-on puts its proxy in front of all traffic, and long-lived SSE connections don't fit. |
| Requests and limits | CPU request = 1, memory request = memory limit = 2Gi (the reference budget). No CPU limit, or one equal to the request: CFS throttling hurts tail latency. |
| VPA | Recommendation-only (`updateMode: "Off"`) to validate requests. Never VPA and HPA on the same CPU/memory metric. In-place resize (stable since Kubernetes 1.35) can't shrink a Python process's memory without a restart. |
| Node autoscaling | Karpenter or Cluster Autoscaler size nodes from *requests*, so accurate requests matter. Add a PodDisruptionBudget (e.g. `maxUnavailable: 1`), because consolidation evicts pods. |
| Termination | `preStop` sleep of about 5–10 s (built-in `sleep` action, Kubernetes 1.30+) so endpoint removal propagates before shutdown starts. `terminationGracePeriodSeconds` > preStop + `GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS`. |
| Probes | `startupProbe` and `readinessProbe` on `/health/ready`, `livenessProbe` on `/health/live` (never touching the database, `NFR-0008`). |

### Phase 8: canary readiness (needs an NFR)

Same scope as Phases 4 and 7: app-side rules, checks and environment
variables only. The goal is that a progressive-delivery controller
(Argo Rollouts or Flagger, splitting traffic through an ingress, the
Gateway API or a mesh) can run old and new versions side by side
against one database, compare them in Prometheus, and roll back
automatically.

**Already in place:** stateless pods (Phase 7), and parallel API
versions over one current-shape model (`ADR-0002`, `NFR-0003`).

**App-side work:**

1. **Migrations never run from a canary pod.** Phase 4's
   `RUN_MIGRATIONS_ON_STARTUP=false` stops pods from migrating the
   shared database at startup. Otherwise the first canary pod would
   change the schema under the stable version, and a rollback wouldn't
   undo it. Migrations run as a separate step before the rollout.
2. **Expand/contract migrations (new NFR-0027):**
   - Every migration must work with the *previous* release's code.
   - Breaking changes are split up: *expand* (add columns or tables,
     backfill in batches), switch the code over, then *contract* (drop
     the old structures) in a later release, after the previous one is
     fully rolled out.
   - Past one-step conversions such as
     `convert_hero_superpower_to_powers_list` are the pattern this
     forbids from now on. Applied migrations stay untouched
     (`NFR-0019`).
3. **N-1 compatibility check in CI:** a new `migration-compat.yml`,
   run on PRs touching `alembic/versions/` or models, inside the
   devcontainer like `checks.yml`:
   - migrate a fresh database to the PR's head;
   - check out the latest release tag into a worktree;
   - run that tag's integration and e2e suites against the migrated
     database, with `RUN_MIGRATIONS_ON_STARTUP=false`.

   Older code must not try to migrate a database whose revision it
   doesn't know, so the check only applies from the first release that
   contains `RUN_MIGRATIONS_ON_STARTUP`; until then it reports and skips.
4. **Squawk migration linter (development and CI only):** a `prek` hook
   renders new revisions to SQL (`alembic upgrade <prev>:<rev> --sql`)
   and lints them with `squawk-cli` (Apache-2.0/MIT, pinned in the
   `dev` group). It flags locking and rewriting operations (adding a
   NOT NULL column without a default, non-concurrent index creation,
   type changes) that would stall a live database during a rollout.
   Squawk never runs in operations and isn't a runtime dependency. It's
   Postgres-specific, which matches the app: Postgres is the only
   supported database (Decision log).
5. **Version on all telemetry:** set `service.version` from the release
   version, passed into the image as a build arg and env variable,
   alongside the OCI version label. `/health/info` (N1) shows the same
   value. Document the per-version error-ratio and p95 queries the
   canary analysis uses, split by `service_version`.
6. **Cross-version data:**
   - MQTT event payloads only ever gain fields, never rename or remove
     them, because events are read by both versions (`ADR-0015`,
     `ADR-0017`).
   - Phase 6 cache keys include the app version wherever a cached
     response's shape can change between versions.
7. **Web UI version skew:** a page served by one version may submit to
   the other. Keep form fields and web-component endpoints compatible
   across one release. Where that isn't possible, the deployment pins
   web traffic per user with a header or cookie match (both controllers
   support it).

**Deployment notes for later (not implemented here):**

| Concern | Setting |
| --- | --- |
| Controller | Argo Rollouts (with Argo CD) or Flagger (with Flux). Pick whichever matches the GitOps tool in use. |
| Traffic split | Ingress or Gateway API weights, or a mesh (e.g. Istio) when header/cookie pinning is needed |
| Steps | e.g. 5% → 25% → 50% → 100%, each held for several analysis intervals |
| Analysis | Prometheus: error ratio and p95 of `http.server.request.duration` per `service.version`. Roll back automatically on breach. |
| Migrations | A migration Job before the first canary step, against `<cluster>-rw` directly (Phase 4). Contract migrations ship only in a later release. |

### Testing this properly (summary of Phase 0 rules)

- Test the production image (`runner`) against real backing services,
  never `MODE=mock` or `--reload` (`ADR-0010`). The `MODE=mock` ASGI
  microbenchmark is the only exception, because it measures framework
  overhead.
- Pin the hardware (CPU and memory caps), warm up, hold each load step
  for minutes rather than seconds, and repeat runs.
- Judge on p95/p99 and error rate at a fixed load (regression), plus
  max sustained users within the SLO (capacity). Average latency hides
  the tail that fails first, which is what the video saw at every
  cliff.
- Report app CPU and RSS with every result. Hitting the same capacity
  at half the CPU is a real improvement.
- Change one variable per run, and keep a flame graph with every
  accepted change.

### CI

Keep the split from `ADR-0010`: noisy wall-clock load tests don't gate
PRs. Add a low-noise per-PR layer.

| Layer | Trigger | Tool | Gate |
| --- | --- | --- | --- |
| Microbenchmarks (`tests/bench/`) | every PR and push to `main` | `pytest-benchmark` run through [CodSpeed](https://codspeed.io/) simulation mode, which counts instructions instead of wall-clock time, so shared-runner noise mostly disappears | CodSpeed's PR regression report. Fail above a set percentage. |
| Fixed-load regression (existing `perf.yml`) | weekly + `workflow_dispatch` + PRs labelled `perf` | Locust, against the CPU-capped stack from `compose.perf.yml` | `NFR-0024` absolute ceilings (as today), plus a relative check against the latest `main` run's JSON summary, downloaded as an artifact (fail if p95 is more than X% worse). |
| Capacity search | `workflow_dispatch` only | Locust `LoadTestShape` | None (report only). Publishes max users, CPU, RSS and the py-spy flame graph as artifacts. |

Notes:

- `perf.yml` already honours `vars.CI_RUNNER`. A dedicated self-hosted
  runner, even a small fixed VM, makes the relative check far more
  trustworthy than shared `ubuntu-24.04` runners.
- **CodSpeed (decided):** the requirement was a service with a good
  long-term track record among open-source projects. CodSpeed has run since
  2022, and Pydantic and Astral (ruff, uv) use it in CI. Its Free plan
  is "forever free" with unlimited users for open-source projects (this
  repo is public), and its client tooling (`CodSpeedHQ/action`,
  `pytest-codspeed`) is MIT-licensed. Lock-in is low: benchmarks stay
  plain `pytest-benchmark` tests, so dropping CodSpeed means swapping
  the CI step, not rewriting tests.
- **Fallbacks if CodSpeed ever stops fitting, in order:** [Bencher](https://bencher.dev/) (since 2020,
  core MIT/Apache-2.0 with a proprietary "plus" tier, self-hostable,
  smaller adoption, with Rustls and Diesel as case studies), then
  `pytest-benchmark --benchmark-compare` with `github-action-benchmark`
  (no external service, wall-clock, needs generous thresholds).
- Adding a per-PR benchmark job and a fifth test suite amends
  `ADR-0010`: record it as a new ADR rather than editing the accepted
  one.
- After Part A, `crud`'s and observability's microbenchmarks (repository
  filtering, router factories, health registry, log formatting) live and run in their
  own repos through the package template's CodSpeed workflow. This
  repo's `tests/bench/` keeps the app-level ones (token verification,
  the ASGI round trip).

## Decision log

Decisions already made, so executing agents don't reopen them. The
orchestrator appends to this list as it resolves escalations.

| Date | Decision |
| --- | --- |
| 2026-10-17 | 1 vCPU / 2 GB is the reference budget for all capacity numbers. |
| 2026-10-17 | No caching of verified tokens. RS256 verification is ~48 µs, and the security cost outweighs that. |
| 2026-10-17 | CodSpeed for per-PR microbenchmarks. Bencher, then `github-action-benchmark`, are fallbacks only. |
| 2026-10-17 | `DB_POOL_MODE` (`null`/`local`/`external`), default `null`. |
| 2026-10-17 | CloudNativePG is kept in mind as a target only: env variables in the app, nothing operator-related in the devcontainer, compose or CI. |
| 2026-10-17 | OTel metrics and traces pushed over OTLP. No `/metrics` endpoint. |
| 2026-10-17 | Packages and the package template are GPL-3.0 for now. |
| 2026-10-17 | Names: `template-python-package`, `tool-crud` / `tool-observability` repos, `craftainer-tool-*` on PyPI, `craftainer_tool_*` imports. |
| 2026-10-17 | Postgres is the only supported database (asyncpg driver, `ARRAY`/`JSONB` types). Supporting MariaDB, Oracle etc. would be a separate portability project. |
| 2026-10-17 | Squawk lints migrations in development and CI only; it is never a runtime or operations dependency. |
| 2026-10-17 | Canary readiness: app-side only. Expand/contract migrations, N-1 compatibility check, `service.version` on telemetry; no rollout controller in this repo. |
| 2026-10-17 | `health` grows into `craftainer-tool-observability`: health, dependency checks, logging, OTel, request IDs, opt-in info/profiling, with extras. No readiness drain (Kubernetes handles it), no problem details, no `/metrics`. |
| 2026-10-17 | Shared server-side caching only for non-per-user aggregates (`/stats`, `/predict`). Per-user responses get `ETag`/`304` with `Cache-Control: private` only. |
| 2026-10-17 | uvicorn stays the default server. Granian replaces it only if it wins the capacity A/B at the reference budget. |
| 2026-10-17 | Not now: Python JIT, free-threaded build, gzip in the app. |
| 2026-10-17 | At most one top-level `Dockerfile` per repo: the runtime image. A devcontainer-only Dockerfile lives in `.devcontainer/` (`template-base#12`). |
| 2026-10-17 | Bench acceptance: keep a change only if its median capacity (3 runs) beats the baseline by more than the run-to-run spread and by ≥ 3%. |
| 2026-10-17 | Non-blocking questions are batched per wave. |
| 2026-10-17 | Concurrency capped at 4 agents: 8 GB host, measured `mypy` peak of about 500 MB per run. |
| 2026-10-17 | Permission rules live in the shared `.claude/settings.json` (allow routine commands, ask on release/variable changes, deny publishing, force/main pushes, merges, repo deletion). |
| 2026-10-17 | Standing approvals: create the three new repos; push branches and open PRs; trigger template-base releases. The user merges all PRs and approves `tool-*`/template releases. PyPI publishing happens only inside `release.yml`, never by hand. |
| 2026-10-17 | Autoscaling: app-side readiness only in this repo. No scale to zero, at least 2 replicas, KEDA on in-flight requests preferred over CPU-only HPA, never VPA and HPA on the same metric. |
| 2026-10-17 | Integration branch is `integration/packages-perf-observability`, cut from `07154b9`; `L1`'s baseline image is built from that commit. |
| 2026-10-17 | W0's write set also covers stale path references in `docs/system-design.md`, FR-0022, FR-0023 and `.devcontainer/stack/mqtt/README.md` (path-only edits). Accepted ADRs and NFR-0023 stay as written; X1 supersedes NFR-0023. |
| 2026-10-17 | `pyinstrument` is a `dev` dependency only; N1's profiling hook imports it lazily (matches A6's pins, which omit `[profiling]`). |
| 2026-10-17 | `OTEL_SERVICE_NAME=template-fastapi` (today's `Settings.app_name` default) in `compose.yml` and `.devcontainer/compose.instance.yml`; the devcontainer needs a rebuild for it to apply. |
| 2026-10-17 | D1 creates `src/app/db.py` exposing module-level `engine: AsyncEngine` and `session_factory: async_sessionmaker[AsyncSession]` (`NullPool`, as today), placed between `health_checks` and `config` in the app layers contract. D2 and `app.maintenance` take the engine from there; E1 extends the same module in Wave 2. D1 may change the single `engine` import line in `app/health_checks.py` to `from app.db import engine`; D2 owns the rest of that file. |
| 2026-10-17 | App version and commit reach the running image as env `APP_VERSION` / `APP_COMMIT` (R1: runner-stage `ARG`/`ENV` in `Dockerfile`, `--build-arg APP_VERSION=$(RELEASE_VERSION)` in `Makefile`, which joins R1's write set). O1 sets `service.version` from `APP_VERSION` unless `OTEL_RESOURCE_ATTRIBUTES` already sets it; N1's `/health/info` reads the same variables. |
| 2026-10-17 | Executors run `pytest tests/unit` only, with `--cov-fail-under=0`, and report uncovered lines in their write set. A bare `pytest` also collects `tests/integration` against the shared services. The 100% gate is checked in the verification lane. |
| 2026-10-17 | The Agent tool's `isolation: "worktree"` bases worktrees on `07154b9`, not the integration branch, and the shared `snip hook` refuses git inside agents. User decision: the orchestrator does all git. It creates each `.claude/worktrees/wip-<id>` worktree (branch `wip/<id>`) from the integration branch; executors only edit files and run checks there, never git; the orchestrator reviews and commits their diff. Executors must not bypass the hook (e.g. by calling `/usr/bin/git`). |
| 2026-10-17 | Each executor worktree has its own venv (`UV_PROJECT_ENVIRONMENT=<worktree>/.venv`), mypy cache (`--cache-dir <worktree>/.mypy_cache`) and no pytest cache (`-p no:cacheprovider`). The shared `~/.venv` has an editable install pointing at `/workspace/src`, so a shared venv would test the wrong tree. |
| 2026-10-17 | S1 escalation (production `POSTGRES_SSLMODE` guardrail would break `smoke.yml`/`perf.yml`, which run `compose.yml` in production mode): keep the guardrail, and S1 also owns `compose.yml` to set `POSTGRES_SSLMODE=require` and serve TLS from the smoke stack's Postgres, following its existing Keycloak/Redis/S3 TLS pattern. The orchestrator verifies the smoke stack in its lane. |
| 2026-10-17 | S1 reported adding `POSTGRES_SSLMODE: require` to the smoke `api` service but hadn't; the orchestrator added it (`9d4dcd4`). The smoke Postgres serves TLS (`show ssl` = on), but the app still connects in cleartext (`pg_stat_ssl.ssl` = f) because nothing consumes `postgres_sslmode` yet: **E1's brief must pass it to asyncpg and require the smoke stack to show `t`.** |
| 2026-10-17 | W0 bug: hatch wheel `packages` listed `src/craftainer_tool_observability/health`, so the runner image lacked `craftainer_tool_observability.logs`; fixed in `9d4dcd4`. The devcontainer's editable install hides wheel-content bugs, so the orchestrator runs the smoke stack (`docker compose -f compose.yml up --build --wait`, unique `COMPOSE_PROJECT_NAME`, then `down --volumes`) whenever an item touches packaging, `Dockerfile`, `compose.yml` or app wiring. |
| 2026-10-17 | D1 put the crud wiring (`configure(CrudConfig…, session_factory)` and `bulk_rate_limit`) in a new `src/app/crud_1/wiring.py`, not `main.py`, because resource routers are built at import time. Accepted; M1 keeps or relocates it. `get_session_factory()`'s unconfigured branch carries a narrow `# pragma: no cover` (e2e can never reach it; unit tests cover it), per the `app/config.py` convention. |
| 2026-10-17 | Executor run isolation, on top of the earlier venv/mypy rules: every executor `pytest` run sets `COVERAGE_FILE=<worktree>/.coverage` (the shared `data_file` with `parallel = true` lets one run's start wipe another's data; verified that `COVERAGE_FILE` overrides it) and `-o cache_dir=<worktree>/.pytest_cache` (`-p no:cacheprovider` fails under `--strict-config`). The verification lane runs only when no executor is running tests. |
| 2026-10-17 | The user removed the `deny` list from `.claude/settings.json` (uncommitted, user's change) to test whether it caused the classifier refusals; it didn't. Permission rules are evaluated against the hook-rewritten command (`snip run -- …`), so the deny rules weren't matching rewritten commands anyway. Whether to restore them is the user's call; until then the orchestrator asks before any merge, publish, release or deletion. |
| 2026-10-17 | Commit/merge workflow while the snip blocker stands: the orchestrator commits and merges with short single-line commands (`git -C <worktree> add -A`, `git commit -m "…"`), never heredocs or compound commands; if the classifier refuses, it stops and hands back to the user. It never works around a refusal. |
| 2026-10-17 | O1 adds `otel.py` and trace-correlation branches in `logs.py` that the running app doesn't reach until M1 wires them, so e2e coverage on `829ddc6` is 97% (missing: `otel.py` 20-85, `logs.py` 61, 69-71, 82-86; unit coverage 100%). User decision: track it as a known gap, with no omit or pragma. Until M1 merges, the verification lane accepts e2e only if its missing lines are exactly that set. **M1's brief must close it**: wire `instrument_app`/`instrument_engine` and run e2e with tracing enabled so both files reach 100%. |
| 2026-10-17 | Batch P1/P2/P3/R1 brief decisions: P1 and P2 share `tests/perf/README.md` (P1 owns a new "Resource sampling and profiling" section, P2 the rest); P3 also owns `tests/bench/README.md` and the suite list entry in `tests/README.md`; R1 also owns the `runner.sh` entry in `scripts/README.md`. P1's `stats.py` JSON schema is the interface P2's `--summary-json` embeds under `api_resources`. P3 covers only app-level benchmarks (token verification, ASGI round trip); crud/observability benchmarks move with the packages. R1 keeps every new uvicorn/Granian tunable env-driven and unset by default (native `UVICORN_*`/`GRANIAN_*` env support) except explicit `--loop uvloop --http httptools`, so L1 A/Bs each variable without a rebuild. |
| 2026-10-17 | P1's sampler/profiler need the template-sync manifest too: `compose.perf.yml` is classified next to `compose.yml` in `.github/template-sync-manifest.yml` (orchestrator edit). P2: custom Locust args never show in `locust --help` (Locust parses `--help` before importing the locustfile); evidence is the `--perf-mode bogus` choices error instead. NFR-0024 has no p99 ceiling, so capacity mode uses 2x the endpoint's p95 ceiling (`--capacity-p99-factor`), matching the challenge's p95 < 500 ms / p99 < 1 s rule. R1: Granian has no graceful-shutdown timeout; `GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS` maps to `GRANIAN_WORKERS_KILL_TIMEOUT`. |
| 2026-10-17 | Pre-existing harness bug found in the P2 smoke: run from the devcontainer, `tests/perf/locustfile.py` mints tokens from the devcontainer's Keycloak (`http://keycloak:8080`), while the `compose.yml` stack's api expects issuer `https://keycloak:8443`, so ~70% of requests get 401 (reproduced with the pre-P2 locustfile). `perf.yml` avoids it in CI via `/etc/hosts`, the stack's cert and `OIDC_TOKEN_URL`. A follow-up item P2b makes local runs work without `.devcontainer/` changes and fixes the summary's `workers` count (taken at quit, after workers disconnect). L1's baseline waits for P2b. |
| 2026-10-17 | Observed in R1's runs and the smoke stack: uvicorn's own log lines (`INFO:     Shutting down`) are plain text, not JSON, which ADR-0007 says they should be. Pre-existing; to be confirmed against `07154b9` and handled as its own item, not inside R1. |
| 2026-10-17 | The known e2e gap grows with N1 (its code is unwired until M1, like O1's): on `1356a44` e2e misses `health/router.py` 19-26, 69-72; `logs.py` 64, 72-74, 85-89; `middleware.py` (26%); `otel.py` (0%); `profiling.py` (0%). Nothing else. **M1's brief must close all of it** (wire `RequestIDMiddleware`, `instrument_app`/`instrument_engine`, and run e2e with tracing on, `include_info=True` and profiling exercised under a non-production mode). N1's final signatures: `RequestIDMiddleware(app, header_name="X-Request-ID")`, `get_request_id()`, `build_health_router(get_registry, *, include_info=False, info_package=None)`, `install_profiling(app, *, enabled, production, query_param="profile")` (raises `ProfilingDisabledError` in production). Span attribute: `http.request.header.x-request-id`. No `[profiling]` extra exists; pyinstrument stays dev-only (earlier decision). |
| 2026-10-17 | V1: the Squawk hook runs with `--changed-only` (frozen migrations, NFR-0019, aren't re-linted under `--all-files`). Squawk's `require-lock-timeout`/`require-statement-timeout` rules stay enabled; a later item should set the timeouts once in `alembic/env.py` instead of in each migration. `migration-compat.yml` skips until a release's `src/app/config.py` contains `RUN_MIGRATIONS_ON_STARTUP`. |
| 2026-10-17 | Pre-existing: `compose.yml`'s production-mode stack had no MQTT broker, so every hero write returned 500; that's why the weekly `perf.yml` on `main` has failed since at least 2026-09-28. User decision: fix it in `compose.yml` (item M0): a TLS + password Mosquitto `mqtt` service, `DNS:mqtt` on the smoke cert, and api `MQTT_HOST`/`MQTT_PORT`. P2b: local perf runs authenticate through `PERF_OIDC_CONNECT_URL` (see `tests/perf/README.md`); CI's `perf.yml` is unchanged. |
| 2026-10-17 | The bulk-action rate limit is per client IP and every Locust user shares one IP, so `compose.perf.yml` sets `RATE_LIMIT_BULK_ACTION=1000000/minute`: only the threshold changes, and the limiter's Redis round trip stays in the measured path. **P5 must make `perf.yml` layer `compose.perf.yml`**, otherwise CI's fixed run still gets 429s. |
| 2026-10-17 | Q1 findings (input for Wave 2 briefs). (a) Response path is already on FastAPI's Rust serialization fast path everywhere hot; no double validation. F1: bulk DELETE (`crud_router.py:400-406`, `response_model=None`) goes through `jsonable_encoder`, so return `Response(model_dump_json())` (LOW); memoize `field_specs(schema)` (`crud_query.py:147-161`, LOW-MED). That means **F1's write set gains `crud_query.py`**. (b) F2, HIGH: a per-row `session.refresh()` after flush in `update_many`/`delete_many`/`restore_many`/`create`/`update` (`repositories/sqlalchemy.py`) should become one `populate_existing` reload query per batch or RETURNING/eager_defaults; owner-scoped single writes take the same path. MED: the delete snapshot `session.get` in `interfaces/base.py:726`, so decide F2's write set at brief time. LOW: `_column()` rebuilds `columns.keys()` per term. No `count()` on lists. F3, CONFIRMED: slowapi does a sync Redis EVALSHA on the event loop for bulk routes and `/mock/token`. Fix: a `RateLimit` decorator over `limits.aio` (`async+redis`), raising `RateLimitExceeded` so the 429 problem details are unchanged. Full notes are in the orchestrator's session; the essentials are here. |
| 2026-10-17 | R2's interfaces for M1: `async def prefetch_jwks() -> None` (warn-only on IdP outage, no-op in mock mode); `decode_bearer_token` keeps its sync signature; `get_current_claims` uses the new `decode_bearer_token_async`, where a warm JWK-set cache stays on the loop and a miss or first discovery runs in the threadpool. The known e2e gap now also includes `oidc.py`'s `prefetch_jwks` (M1 wires it). The expired-cache branch of `_jwks_is_warm` carries a narrow e2e pragma (unreachable within the cache lifespan; unit-covered). |
| 2026-10-17 | P5: `perf.yml` layers `compose.perf.yml` via `COMPOSE_FILE`; a `fixed` job does the relative p95 check against the latest `main` run's `perf-summary` artifact (`gh run download`, `actions: read`, `PERF_MAX_P95_REGRESSION_PERCENT` default 20, passes with no baseline); a dispatch-only `capacity` job is report-only. `codspeed.yml` uses `CodSpeedHQ/action@v5.5.0` in simulation mode with OIDC (`id-token: write`, no secret), uv on the runner. Neither workflow has run: validate with `workflow_dispatch` once the integration branch is pushed (standing approval), and CodSpeed needs the org-wide app from pre-flight item 3. |
| 2026-10-17 | L1's first baseline attempt (image `perf-baseline:07154b9`, verified 1 CPU / 2 GiB) stopped on two harness issues. (1) Bug: each Locust user logged in once, and the realm's 300 s token lifespan turned every run into 401s after ~5 min; item P2c refreshes tokens before expiry and re-logs in once on a 401. (2) User decision: per-endpoint p95/p99 ceilings apply only to endpoints with at least `--capacity-min-endpoint-samples` (default 100) requests in a step's window; aggregate p95/p99 and error rates always apply. Calibration so far: capacity is roughly 20–35 users at ~1 req/s/user; candidate run parameters are 5-user steps, 150 s, 30 s warm-up, max 60; generator CPU is negligible (max 4% of one core). |
| 2026-10-18 | L1 baseline (Phase 0.7), image `perf-baseline:07154b9` (sha256:286ae359…), 1 CPU / 2 GiB, integration-HEAD harness `8817990`, 5-user steps, 150 s, 30 s warm-up: `max_users_passed` 25 / 30 / 25 (median 25, spread 5). At the last passing step: p95 140–160 ms, p99 200–240 ms, 24–28 RPS, 0 errors, api CPU mean 44–52% of the limit, RSS ~157 MiB. Steps fail on tail latency (list GET, PATCH), not CPU saturation. Time to ready 1.64 / 1.55 / 1.59 s (median 1.59 s). The profile (thin, 38% usable samples) shows Python self time mostly in new TLS connections (SSLContext, handshakes, asyncpg connect, DNS), consistent with NFR-0016's NullPool. Results: `tests/perf/.results/baseline-07154b9/` (gitignored). Three run-2 attempts were invalid because of whole-host stalls (swap 100% used on the 8 GB host); stalls ended once L1 removed its polling watcher. Measurements need the host otherwise idle. |
| 2026-10-18 | User decision, supersedes "Bench acceptance" above: the 3% capacity rule can't resolve anything at 5-user steps, so A/B is judged on **fixed load**. Each variant gets 3 fixed-load runs at 25 users (just below the baseline break point). Keep a change only if api CPU-ms per request or aggregate p99 improves by more than the baseline run-to-run spread and by ≥ 3%, without the other regressing beyond its spread. Capacity is a coarse gate: a kept change must not lower median `max_users_passed` by a step. L1 first measures the baseline spread of these fixed-load metrics. |
| 2026-10-18 | L1 fixed-load baseline (07154b9, 25 users, 6 min, first 60 s excluded via a scratchpad-only `stats.reset_all()` listener, 300 s window): CPU-ms/request 18.95 / 19.69 / 19.60 (median 19.60, spread 3.8%); aggregate p99 210 / 210 / 270 ms (median 210, spread 28.6%); p50 60–63, p95 140–160 ms, ~24 RPS, 0 errors. Under the 2026-10-18 rule, a change is kept only for a CPU-ms/request improvement > 3.8%; p99 acts as a regression guard only. Orchestrator follow-ups: P1b makes `stats.py` record exact cumulative container CPU (cgroup `cpu.stat` usage delta) to cut sampling noise, and A/B runs for expected effects of 2–5% are interleaved. Results: `tests/perf/.results/baseline-07154b9/fixed/`. |
| 2026-10-18 | Host stalls (whole-system freezes of 9–15 min, about 1 in 5 perf runs, swap 100% full on the 8 GB host) recur even with no pollers. Stalled runs (sampler gap > 10 s or worker heartbeat errors) are discarded and repeated. Reported to the user as an environment issue. |
| 2026-10-18 | Wave 2 batching: A = P1b, E1, F1, F2; B = F3, C2, H1, X1; C = M1 (after E1/C2 interfaces exist), X2; L1 A/B in quiet windows afterwards. Write-set decisions: F1 also owns `controllers/crud_query.py`; F2 also owns the delete-snapshot and double-`model_dump` spots in `interfaces/base.py`; E1 also owns the `DB_POOL_MODE=local` env line in `compose.yml` (Phase 3 step 2). E1's interface for M1: `app.db.engine`, `app.db.session_factory`, `app.db.build_engine(settings)`. Executors write but don't run integration tests; the orchestrator's lane runs them. |
| 2026-10-18 | Wave 2 batch A merged and verified: P1b `189df64`, E1 `1cbc6ed`, F2 `6059aaf`, F1 `f4bd1a6`. Unit+integration coverage stays at 100%; F2's round-trip tests pass (create has no SELECT, bulk ops use 2 statements). Smoke stack: `DB_POOL_MODE=local`, `POSTGRES_SSLMODE=require`, and `pg_stat_ssl` shows the api's 5 pooled connections all on TLS (was `f`). F2 skipped the optional `interfaces/base.py` items: the snapshot reuse would change snapshot content, and dump-once would change signatures. Both are left as possible later work. |
| 2026-10-18 | The e2e gap now also contains E1's config branches in `app/db.py` (SSL, timeouts, `local`, `external`): the e2e app process runs with defaults. **M1's brief must close it** by starting the e2e app with deployment-like settings (`DB_POOL_MODE=local`, `DB_CONNECT_TIMEOUT`, `DB_COMMAND_TIMEOUT`, `POSTGRES_SSLMODE=prefer`, which works against the devcontainer's plaintext Postgres). M1's write set gains `tests/e2e/conftest.py` for this. Only the `external` branch takes a narrow e2e pragma (Phase 3 step 3: unit-tested only). |
| 2026-10-18 | P1b: `stats.py` records exact cgroup CPU (`summary.cpu_seconds_total`, per-sample `cpu_usage_usec`, `cpu_seconds_between()`). On an idle container the old `docker stats` mean understated CPU ~2.6x, so the 2026-10-18 fixed-load baseline (19.6 CPU-ms/req) is not comparable with exact-method numbers. **L1 re-measures the fixed-load baseline with exact CPU before any A/B.** |
| 2026-10-18 | Wave 2 batch B merged and verified: X1 `72384d8`, H1 `4bd0b7f`, F3 `068e2c4`, C2 `0d0109e`. H1's SIGTERM/SSE test passes (exit within timeout; lossless resume keyed on the stream's `subscriber_id` sent as `Last-Event-ID`), so no shutdown hook is needed. F3 uses `limits.aio` with `implementation="redispy"` (no coredis dependency); live: 0 errors on the capped stack, 429s on PATCH at the default 20/minute on the plain stack. C2 keys omit roles (they gate access, not content); `cache_scope` reads CRUD private attributes, so a public `read_scope` property is a follow-up. fastapi-cache2 was rejected (last release July 2024, pins `redis<5`). |
| 2026-10-18 | The known e2e gap now also contains C2's unwired cache code and F3's `rate_limit.py`, whose logic used to live inside slowapi. **M1 closes the whole gap**: it starts the e2e legs with deployment-like env plus an in-process OTLP/HTTP stub receiver (the devcontainer has no collector; a test stub, not a new service), adds journeys, and may use narrow pragmas only for the listed defensive or e2e-unreachable branches. Batch C = M1, C1 (Wave 2b; F1 is merged), X2. M1 alone runs e2e this batch. |
| 2026-10-18 | M1 escalation (e2e at 99.11% after the three-leg rework: dev with every feature on plus an OTLP stub receiver, mock, and bare with all defaults). Orchestrator decision: restructure two lines (`rate_limit.py` URI normalization without a branch; `InMemoryStatsCache` keys versioned like Redis, Phase 8.6). Narrow e2e pragmas with reasons for the remaining defensive, failure-path, config-guard and production-only lines in `cache.py`, `oidc.py`, `crud_router.py`, `crud_stats.py`, `health/router.py` and `profiling.py`, all unit-covered. The owner-scoped `cache_scope` line is security-relevant, so it requires a unit test that different owners get different keys. |
| 2026-10-18 | Pre-existing bug found by M1, and the root cause of the 2026-10-17 "uvicorn log lines aren't JSON" observation: `alembic/env.py`'s `fileConfig(...)` replaces the root logger's handlers, so any process that migrates on startup loses JSON logs and the OTLP log bridge (no `request_id`/`trace_id` in logs). Separate item A7 after M1: keep the existing handlers when `fileConfig` runs (or skip it when the root logger is configured), then extend the e2e log journey to the dev leg. |
| 2026-10-18 | C1: strong ETag on single GETs (id + `updated_at`, falling back to a JSON hash), weak ETag on lists, `Cache-Control: private, no-cache`, 304 on `If-None-Match`, 412 on a stale `If-Match` for single-record PATCH/DELETE (bulk actions unconditional; weak tags never match `If-Match`; the check-then-write race is documented). Locust `--revalidate-weight` defaults to 0, so the baseline mix is unchanged. X2: ADR 0022/0023 and NFR-0026 drafted; ADR-0006 and NFR-0016 get status lines only. |
| 2026-10-18 | Wave 2 batch C merged: X2 `04229d8`, C1 `fad2dee`, M1 `6c3bc8b`, plus orchestrator fix `0effb83`. C1's `If-Match` lookup used `include_archived=True`, so a PATCH on a record archived by DELETE answered 412 instead of the write's 404 (the e2e journey caught it on the Postgres legs); the precondition now uses the write's own `?include_archived`/`?include_unpublished` visibility. **First fully green suite since O1, e2e at 100% included.** Production smoke: docs routes 404, `/health/info` 404 (off by default), `X-Request-ID` echoed, pooled connection on TLS, clean lifespan shutdown, 0 tracebacks; log lines are still plain text, the alembic bug A7 fixes. Follow-ups: public `read_scope` property on CRUD interfaces (C2); `docs/system-design.md` and `src/README.md` should mention the `cache` layer and M1's wiring. |
| 2026-10-18 | A7 merged and verified (`3b28bc5`): `alembic/env.py` runs `fileConfig` only when the root logger has no handlers, and `configure_logging()` routes uvicorn's loggers (which uvicorn gives their own plain handlers with `propagate=False`) to the root JSON handler. Production smoke shows 0 non-JSON log lines. Side effect for benchmarks: the access log is now JSON-formatted per request; R1's `UVICORN_ACCESS_LOG` toggle measures that cost. |
| 2026-10-18 | L1 measurement program (orchestrator decision): (1) re-baseline `07154b9` with exact cgroup CPU (fixed load, 3 runs); (2) HEAD image with baseline-equivalent env (`DB_POOL_MODE=null`), measuring all code changes combined; (3) single-variable env A/Bs on the HEAD image: `DB_POOL_MODE=local`, `UVICORN_ACCESS_LOG=false`, `GC_FREEZE=false`, `APP_SERVER=granian`. Per-merge images (F1/F2/F3/R2 one at a time) only if (2) is not better than (1). The acceptance rule is the 2026-10-18 one (CPU-ms/request beyond the spread and ≥ 3%; p99 as a guard; capacity as a coarse gate, checked for the kept variants). |
| 2026-10-18 | Pre-flight complete. Org rulesets aren't enforced on the Free plan (the org ruleset the user created shows as disabled; the user deletes it). Instead the orchestrator copies `template-fastapi`'s two repo-level rulesets exactly (`gh api repos/craftainer/template-fastapi/rulesets/<id>` → `POST repos/craftainer/<repo>/rulesets`, dropping `id`/`source`/timestamps): "Disallow direct push to main" (default branch: no deletion or force push; PR required, squash only, 1 approval, last-push approval, threads resolved, stale reviews dismissed; bypass: org admins and Renovate, app 2740) and "Disallow tags except me" (all tags: no deletion, update or force push). No required status checks are added. Timing: `template-python-package` right after it's created; `tool-crud`/`tool-observability` right after A5's `git filter-repo` history lands on `main` (squash-only would flatten it), before any other PR merges there. `TEMPLATE_SYNC_TOKEN` is visible to all public repos (the Free plan's widest), so all three new repos must stay public. |
| 2026-10-18 | template-python-package placeholders (orchestrator decision): distribution `template-python-package`, import `template_python_package`, Python >= 3.14, hatchling + uv, version `0.0.0` stamped at release time from `RELEASE_VERSION`; `PYPI_PUBLISH=testpypi|pypi` selects the index; `tests/unit` (100% gate) and `tests/bench` (CodSpeed). The copied tag ruleset also carries a `required_status_checks` rule that the earlier summary didn't mention; it's copied unchanged ("copy exactly"). |
| 2026-10-18 | G-pr: template-base#14 merged (`74174d4`), so template-base v1.5.0 (full, minor) was triggered by the orchestrator. The user applied the rulesets to template-python-package. PR #2's CodSpeed check failed on two latent bugs that also sat in this repo's never-run `codspeed.yml` (P5): uv picked Python 3.15 on the bare runner (no pin), and pyproject's devcontainer-only `cache_dir` (`/home/vscode/...`) isn't writable there. Fixed in both repos: setup-uv `python-version: "3.14"` and `-o cache_dir=${{ runner.temp }}/pytest-cache`. CodSpeed then passed on #2 (CPython 3.14.8). |
| 2026-10-18 | Wave 3 history import (dry-run verified): `git filter-repo` (run ad hoc via `uvx --from git-filter-repo`, not a repo dependency) on a fresh clone of the integration branch, in **two passes**, because `--paths-from-file` applies `==>` renames before matching. Pass 1 keeps the original paths; pass 2 renames them to the package layout. crud: `src/crud/`, `src/craftainer_tool_crud/`, `src/app/{xml_codec,web_components}.py` → `src/craftainer_tool_crud/`; `tests/unit/{crud,craftainer_tool_crud}/` → `tests/unit/`; `tests/integration/crud/` → `tests/integration/` (30 commits). observability: `src/health/` → `.../health/`, `src/app/telemetry.py` → `.../logs.py`, `tests/unit/{health,craftainer_tool_observability}/`, `tests/unit/test_telemetry.py` → `tests/unit/test_logs.py` (16 commits). Each new repo's `main` gets the template scaffold merged with the filtered history (`--allow-unrelated-histories`), pushed before the rulesets go on (the user applies them; auto mode refuses), then K1/K2 adapt via PRs. Several moved crud tests import the app's `Hero`/`app.db`; K1 replaces them with package-local fixtures. |
| 2026-10-18 | **L1 interim A/B** (exact cgroup CPU, fixed load at 25 users, n=2 each; c3-r2 discarded as a host-stall outlier). CPU-ms/request median: baseline `07154b9` 22.5; HEAD with `DB_POOL_MODE=null` 19.7 (**-12.7%**, clears the rule); HEAD `local` 7.2 (**-63%** vs null; p99 265 → 69 ms, p50 64 → 11 ms; clears by far). No gain from access log off (the knob turned out to be broken, A8), `GC_FREEZE=false` (+2.1%, so freeze stays on) or Granian (+2.7%, more RSS, so uvicorn stays the default; ADR 0024 isn't written). Final numbers after the third runs and the capacity runs. Capacity at `local` will likely exceed the old 60-user ceiling, so the resume raises `--capacity-max-users`. |
| 2026-10-18 | Root cause of the whole-host freezes (2026-10-18 entry): `docker exec`/`docker stats` calls during a run (`stats.py`'s 2 s sampling). Runs without them were clean. L1 now reads cgroup `cpu.stat`/`memory.peak` directly from the devcontainer at window boundaries. P1c makes `stats.py` docker-free during sampling. A8: A7's uvicorn re-routing re-enables `uvicorn.access` even with `UVICORN_ACCESS_LOG=false`; A8 fixes it here, and the orchestrator ports the fix into tool-observability (K2), whose history was imported before the fix. |
| 2026-10-18 | K1/K2 decisions accepted: tool-crud's 100% gate includes `tests/integration/` (the repository's Postgres-only SQL; CI runs prek in the devcontainer with `compose.instance.yml`'s Postgres); SQLAlchemy capped `<2.1` in both packages (K1: 2.1's `Select`/`Row` typing breaks mypy; K2: the OTel SQLAlchemy instrumentation supports `< 2.1.0` only); `python-multipart` is a crud core dependency; tool-observability drops e2e-only pragmas (100% on unit tests alone); instances delete the template's own ADR 0001. Release fix: template-base's `release.yml` runs `build`/`sbom`/`publish` on the bare runner without uv, so the package Makefile falls back to the pinned `ghcr.io/astral-sh/uv:0.13.0-python3.14-trixie-slim` image (runner uid, OIDC variables forwarded), like the `sbom` target's Syft image. The user approved template-python-package v1.0.0 (G-rel). |
