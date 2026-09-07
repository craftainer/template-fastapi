# Extract a stripped-down `template-base` and keep it in sync

## Status

Draft

## Goal

`template-fastapi` bundles two things that are currently inseparable:
a generic "devcontainer + CI + AI-assisted workflow" scaffold, and a
full FastAPI/Postgres/Redis/S3/Keycloak application skeleton on top of
it. A wider family of repos only wants the first part: a library (Python,
Node.js, ...), an infra-only repo (OpenTofu/Ansible/Kubernetes/Docker
Compose, no app runtime at all), or even a full application port of
`template-fastapi` itself into another language (Rust, Go, Node.js) —
none of these want FastAPI's application code or backing services, but
all of them want the same devcontainer conventions, CI/release/
template-sync machinery, `.claude`/`.vscode` config, and docs/ADR/plan
scaffolding.

This plan extracts that generic subset into a new template repo
(`template-base`), makes `template-fastapi` itself consume `template-base`
via the sync mechanism this repo already ships (rather than inventing a
second one), and does both without breaking `template-sync.yml` for
repos that already use `template-fastapi` as their template.

## Approach

### 1. The shape: `template-fastapi` becomes an instance of `template-base`

`template_sync.py`'s `apply` step only ever touches paths that match a
pattern in the manifest it's given (`tier_paths` walks the manifest's
own `replace`/`merge` globs — it never scans the instance tree for
"extra" files to delete, see `apply_replace`/`apply_merge` in
`.github/scripts/template_sync.py`). That means a repo can safely be an
instance of a template whose manifest only covers a *subset* of the
instance's own files: everything not matched by that manifest is simply
never touched.

So no new sync tooling is needed. `template-base` gets its own
`.github/template-sync-manifest.yml` covering only the generic subset it
actually ships, and `template-fastapi` is bootstrapped as one of its
instances using the existing `workflow_dispatch` `initial_sync_tag`/
`template_repo` inputs (the same path already built for onboarding a
pre-existing repo, see `template-sync.yml`'s "Bootstrap state file"
step). Concretely:

- `template-fastapi` gets a `.github/template-sync-state.json` pointing
  `template_repo` at `craftainer/template-base`. Its
  `template-sync.yml` (unchanged file, already fully generic) then pulls
  updates to base-owned paths from `template-base`'s tagged releases,
  same as any instance does today.
- `template-fastapi`'s **own** `.github/template-sync-manifest.yml` —
  the one that classifies *its* tracked files for *its own* downstream
  instances — is untouched and keeps listing `src/`, `tests/`,
  `alembic/`, `pyproject.toml`, etc. This is a completely separate
  document from `template-base`'s manifest; the workflow always reads
  the manifest from whichever repo is being synced *from*
  (`/tmp/template-new/.github/template-sync-manifest.yml`), never the
  instance's own copy. Downstream repos of `template-fastapi` keep
  pointing at `craftainer/template-fastapi` and keep working exactly
  as they do today — nothing about their state file, manifest, or
  workflow changes.
- The net effect is a two-hop chain: improvements to generic scaffolding
  land in `template-base` → flow into `template-fastapi` via a sync PR →
  flow from `template-fastapi` into its own downstream instances via a
  second sync PR. Each hop is still human-reviewed and PR-gated, never
  auto-merged, matching how sync already works.

### 2. What moves into `template-base`

Classify every currently-`replace`/`merge` path in
`template-sync-manifest.yml` by whether it's genuinely stack-agnostic:

**Straightforward `replace` candidates (no FastAPI/Python content today):**
`.claude/`, `.github/workflows/template-sync.yml`, `.github/scripts/`
(`template_sync.py`, `template_sync_manifest.py` — both stdlib-only and
already document themselves as instance/template-agnostic;
`compute_next_version.py` confirmed generic — it's pure git-tag/SemVer
math with no artifact or language awareness at all), `.github/workflows/
checks.yml` (see "Checks: prek everywhere" below), `.github/ISSUE_TEMPLATE/`,
`.github/PULL_REQUEST_TEMPLATE.md`, `CLAUDE.md` (already
methodology-only, no Python mentions), `docs/README.md`,
`docs/adrs/README.md` + `template.md`, `docs/frs/*`, `docs/nfrs/*`,
`docs/plans/README.md` + `template.md`, `.secrets/README.md` +
`.gitkeep`, `.gitattributes`.

**Checks: prek everywhere.** `checks.yml` today is already almost fully
generic — its only Python-specific line is invoking prek via
`uv run prek run --all-files --hook-stage manual`, because prek is
currently installed as a `uv` dev-dependency. Every future instance
(any language, or infra-only) is still expected to use prek — that's
the one CI convention this plan holds constant across the whole
`template-base` family, only *what hooks run* varies per instance via
its own `.pre-commit-config.yaml`. So `template-base`'s devcontainer
setup installs prek as a standalone tool (e.g. via `uv tool install`,
`pipx`, or a pinned binary release — not as a project dependency of any
particular language's package manager), and `checks.yml` becomes
`runCmd: prek run --all-files --hook-stage manual` with no `uv run`
prefix. That makes the whole file instance-agnostic and a clean
`replace`-tier candidate. `template-fastapi`'s own `.pre-commit-config.yaml`
keeps layering `ruff`/`mypy`/`pytest`/`pip-audit` hooks on top via the
`merge` tier described above; an infra instance's config would instead
layer `tflint`/`terraform validate`/`ansible-lint`; a Rust/Go/Node port
would layer `cargo fmt`+`clippy`, `golangci-lint`, or `eslint`+`tsc`
respectively.

**Release: a generic workflow over a per-instance Makefile contract.**
`release.yml` needs a real per-artifact-type difference — an OCI image
(this repo today), a Helm chart, a PyPI or npm package, or (for an
infra-only repo) possibly no publishable artifact at all beyond the git
tag itself. Rather than writing N variants of `release.yml`, define a
small Makefile contract every instance implements, and keep exactly one
generic `release.yml` in `template-base`:

- `make build` — produce whatever the release artifact(s) are (build the
  image, `cargo build --release`, `npm pack`, `helm package`,
  `python -m build`, `terraform validate`/plan bundle, ...).
- `make sbom` — write an SBOM for what `build` produced, in whatever way
  fits (Syft against an image, `cyclonedx-py`/`npm sbom`/`cargo cyclonedx`
  against a package, or a no-op target for a repo with nothing to scan).
- `make release-assets` — populate one well-known directory (e.g.
  `dist/`) with every file that should be attached to the GitHub
  release; `release.yml` just globs that directory, so it never needs to
  know whether it's attaching a `.tar`, `.whl`, `.tgz`, or a chart
  archive.
- `make publish` — push to whatever registry applies (OCI registry,
  PyPI, npm, a Helm repo), gated the same way `OCI_REGISTRY` gates today
  (skip cleanly when the relevant registry variable/secret isn't set),
  or a no-op target when there's nothing to push.

`release.yml` itself stays in `template-base` as `replace` tier: compute
the tag/version (`compute_next_version.py`, unchanged), run `make build`
/`make sbom`/`make release-assets`/`make publish` in sequence, then
`gh release create` with everything found in `dist/`. Each instance's
`Makefile` is not template-owned (it's the whole point that it differs
per artifact type), so it's tracked like `src/`/`tests/` today —
untouched by `template-base`'s manifest, entirely instance-owned.
`template-fastapi`'s own `Makefile` reimplements today's `release.yml`
steps (image build, `anchore/sbom-action`-equivalent, `docker
build-push-action` publish) as `make` targets; nothing about the
released artifacts themselves changes, only where the logic lives.

**Needs restructuring, not a direct copy:**
- `Dockerfile` — `template-base` ships a single `develop` stage with
  *no* language runtime installed at all: `scripts/develop.sh`'s current
  `uv python install` step is entirely Python-specific and moves to
  `template-fastapi`'s own layer, not `template-base`. Every instance —
  a Python app, a Rust/Go/Node.js port of `template-fastapi`, or an
  infra repo — adds its own runtime/tooling install on top of the same
  base image and `postCreateCommand` hook structure (e.g. a Rust port
  installs `rustup`+`cargo`, an infra repo installs `tofu`/`ansible`/
  `kubectl`, the same way `template-fastapi` installs `uv`+Python
  today). `builder`/`runner` stages don't exist in `template-base` at
  all — a repo that needs to ship a runtime image (any app, in any
  language) adds them itself, following the same three-stage shape
  `template-fastapi` already establishes as the convention, but with
  its own per-language build steps.
- `.devcontainer/` — `compose.yml` and `stack/` are full of
  application-backing services (Postgres/RustFS/Redis/Keycloak/
  Selenium) that a bare library/infra repo has no use for.
  `template-base` ships `devcontainer.json` + a minimal `compose.yml`
  (just the `api`-equivalent dev service, no `include:` of any stack
  fragment) and no `stack/` directory at all; `template-fastapi` keeps
  `stack/` as an addition on top (untracked by `template-base`'s
  manifest, so sync never touches it) and re-adds the `include:` list
  via whatever tier `compose.yml` ends up in (see below).
- `.vscode/` — split generic editor `settings.json` (`replace`,
  shared) from Python-specific `launch.json`/`tasks.json` entries
  (uvicorn debug config) — those stay `template-fastapi`-only.
- `.pre-commit-config.yaml` — `template-base` defines only
  language-agnostic hooks (whitespace/EOF fixers, YAML/TOML lint,
  `conventional-pre-commit`); `template-fastapi` layers `ruff`/`mypy`/
  `pytest`/`pip-audit` hooks on top. Make this `merge` tier (like
  `pyproject.toml` today) rather than `replace`, so `template-fastapi`'s
  additions survive a sync.
- `.github/renovate.json` — `template-base`'s version covers Actions
  and Docker/compose image tags only; `template-fastapi`'s adds the
  Python/`pyproject.toml` package rule. `merge` tier, same reasoning.
- `.gitignore` — `template-base` ships the generic
  (editor/OS/`visualstudiocode`) sections; `template-fastapi` keeps the
  `python`/`venv` sections as its own addition. `merge` tier.
- `README.md` — already `merge`-tier in `template-fastapi`'s own
  manifest for its downstream instances; `template-base` treats it the
  same way one layer up.
- `docs/TEMPLATE.md` — structurally, `template-fastapi`'s version today
  reads as `template-base`'s generic sections plus FastAPI-specific
  ones appended/interleaved (Getting Started, Checks, Versions). Since
  `template-fastapi` is meant to keep evolving its own copy with
  Python-specific detail while still wanting base-level wording fixes,
  treat this as `merge` tier rather than forcing it into `ignore` (which
  would freeze it the moment it diverges).

**Stays `template-fastapi`-only (not tracked by `template-base` at all,
so sync never touches these paths):**
`src/`, `tests/`, `alembic/` + `alembic.ini`, `pyproject.toml`/`uv.lock`,
`scripts/` (all six are Dockerfile-stage/Python-specific — revisit if
any turn out generic enough to hoist later), `compose.yml` (Postgres/
RustFS/Redis/Keycloak smoke stack), `Makefile` (implements the release
contract above with this repo's own build/SBOM/publish steps),
`.github/workflows/smoke.yml`/`perf.yml` (health-check/Locust-load-test
patterns specific to a running HTTP service — not part of the base
contract; an instance with no long-running service, like a library or
most infra repos, simply doesn't have these workflows at all).

### 3. Build `template-base`

1. Create the new repo (`craftainer/template-base`).
2. Seed it from a clone of `template-fastapi`, then delete everything in
   the "stays fastapi-only" list above and trim the "needs
   restructuring" items down to their generic subset per §2.
3. Rewrite `template-base`'s own `docs/TEMPLATE.md` and root `README.md`
   preface to describe the smaller contents (devcontainer `develop`
   stage only, no app framework assumed).
4. Write `template-base`'s own `.github/template-sync-manifest.yml`,
   exhaustive over `template-base`'s own (much smaller) tracked-file
   set — the existing `template_sync_manifest.py` exhaustiveness check
   (run via prek) validates this the same way it does today.
5. Tag an initial release (e.g. `v0.1.0`).

### 4. Bootstrap `template-fastapi` onto `template-base`

1. In `template-fastapi`, run `template-sync.yml` manually with
   `template_repo: craftainer/template-base` and
   `initial_sync_tag: v0.1.0` — this writes
   `.github/template-sync-state.json` without touching any files (per
   the workflow's "Bootstrap state file" step).
2. Immediately trigger a real sync run afterward and inspect the PR: it
   should be empty or near-empty, since `template-base`'s content was
   copied verbatim from `template-fastapi` in §3. A large diff here
   means something in the manifest classification was wrong — fix
   `template-base` before merging, don't force the PR through.
3. Confirm no path under the "stays fastapi-only" list appears in the
   PR at all (proves the manifest scoping is safe, not just
   coincidentally clean).

### 5. Verify the chain both directions

- **Base → fastapi:** land a trivial change in `template-base` (e.g. a
  CLAUDE.md wording fix), tag a new release, run `template-fastapi`'s
  template-sync and confirm the PR picks it up.
- **Fastapi → its downstream instances:** pick (or create) one existing
  instance of `template-fastapi`, run its template-sync unmodified, and
  confirm it still syncs against `craftainer/template-fastapi` exactly
  as before — this is the regression check that this extraction must not
  break.
- **Base standalone:** instantiate two throwaway repos directly from
  `template-base` on opposite ends of the intended range — e.g. an
  infra-only repo (OpenTofu, no `builder`/`runner` stages, no
  `Makefile`/`release.yml` targets beyond a tag) and a small language
  port (a minimal Rust or Go "hello world" service reusing the
  three-stage Dockerfile convention) — and confirm each one's
  devcontainer builds, `prek run --all-files --hook-stage manual` passes
  with only its own hooks layered on, `make build`/`make release-assets`
  (where applicable) work, and its own template-sync bootstraps against
  `template-base` cleanly. Two different shapes catch a base assumption
  ("there's always a `Makefile`", "there's always a `builder` stage")
  that a single Python-flavored check wouldn't.

## Open questions

- **Rust/Go/Node ports of `template-fastapi` itself.** Out of scope for
  *this* plan (which only extracts `template-base`), but worth naming as
  the motivating case for the Makefile/prek contract above: a future
  full port reuses `template-base`'s devcontainer/CI/release shape and
  `template-fastapi`'s own architecture (three Dockerfile stages, health
  endpoints, the CRUD-example pattern) without needing another new
  contract invented for it. No action here beyond keeping that case in
  mind while classifying §2.
- **Makefile target names/interface.** §2 proposes `build`/`sbom`/
  `release-assets`/`publish` as the contract, but the exact target names
  and what `release.yml` passes to them (env vars vs. `make VAR=value`
  args) needs to be pinned down and documented — likely as
  `template-base`'s own `docs/TEMPLATE.md` section — before instances
  can rely on it as a stable interface.
