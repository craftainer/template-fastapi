# workflows/

- `checks.yml` — runs every `prek`/`pre-commit` hook
  (`--hook-stage manual`, so both the fast and extensive ones) on push,
  on pull requests, and on demand — inside the actual devcontainer (via
  [`devcontainers/ci`](https://github.com/devcontainers/ci)), under a
  per-run `COMPOSE_PROJECT_NAME` that a final step tears down.
- `smoke.yml` — builds the `runner` stage of the root `Dockerfile` via
  the root `compose.yml`, starts it against the real Postgres, RustFS,
  Redis, and Keycloak backing services, and confirms `/health/live` and
  `/health/ready` both return 200 -- on push, on pull requests, and on
  demand.
- `release.yml` — manually triggered. Takes a release channel
  (`alpha`/`beta`/`rc`/`full`) and a SemVer 2 bump
  (`major`/`minor`/`patch`/`none`), computes the next tag via
  `../scripts/compute_next_version.py`, builds the `runner` stage of the
  root `Dockerfile`, and creates a GitHub release with auto-generated
  notes and that image attached as an OCI tarball, an SPDX-JSON SBOM
  (via `anchore/sbom-action`/Syft), and a `coverage.xml` report from
  running the test suite against the released commit. The built image
  (both the tarball and, if configured, the registry push) carries
  standard `org.opencontainers.image.*` labels via
  `docker/metadata-action`, plus two custom
  `io.github.<repository_owner>.*` labels pointing at the SBOM and
  coverage-report release assets, so the image is self-describing.
  Also pushes the image to an OCI registry if one is configured (see
  "OCI registry" below).
- `template-sync.yml` — runs in an *instance* of this template, not
  here (see the root `docs/TEMPLATE.md`'s "Template sync" section and
  `../template-sync-manifest.yml`'s header for the full design). On a
  schedule or `workflow_dispatch`, diffs the instance against the
  template's latest tagged release per the manifest's tiers and opens a
  PR — never a direct push, never auto-merged.

Every workflow's `runs-on` defaults to `ubuntu-latest` but can be
overridden with the `CI_RUNNER` repository/organization variable —
e.g. to point at self-hosted runners.

## Template sync

`template-sync.yml` reads its own operating parameters from repository
variables/secrets, all optional:

- `TEMPLATE_SYNC_INTERVAL` (variable, `weekly` | `monthly`, default
  `weekly`) — the workflow still wakes up weekly regardless (cron can't
  read a repository variable to pick its own schedule); on `monthly` it
  no-ops except during the first cron-scheduled week of the month.
- `TEMPLATE_SYNC_CHANNEL` (variable, `stable` | `alpha` | `beta` | `rc`,
  default `stable`) — which tag channel to sync to.
- `TEMPLATE_SYNC_TOKEN` (secret) — a PAT with read access to the
  template repository, if it's private. Falls back to the default
  `GITHUB_TOKEN` (works for a public template).

## OCI registry

`release.yml` only pushes to a registry when the `OCI_REGISTRY`
repository/organization variable is set (e.g. `ghcr.io`,
`docker.io`, or a private registry host) — the push step, the login
step, and the image-name step are all skipped otherwise, so the
workflow works with no registry configured at all. When it is set:

- `OCI_IMAGE_NAME` (variable, optional) — the image path within the
  registry, e.g. `myorg/template-fastapi`. Defaults to the repository's
  own `owner/repo` (lowercased) if unset.
- `OCI_REGISTRY_USERNAME` / `OCI_REGISTRY_PASSWORD` (secrets,
  required whenever `OCI_REGISTRY` is set) — credentials for
  `docker/login-action`.

## Image labels

Both copies of the published image (the OCI tarball and, if configured,
the registry push) carry the same label set, computed once by
`docker/metadata-action`:

- Standard `org.opencontainers.image.title` / `.description` / `.url` /
  `.source` / `.revision` (`github.sha`) / `.created` / `.version`,
  derived from git/GitHub context.
- `io.github.<repository_owner>.sbom` and
  `io.github.<repository_owner>.coverage-report` — URLs to that
  release's SBOM and `coverage.xml` assets. Namespaced under the repo
  owner (not `org.opencontainers.image.*`, which is reserved for the
  spec's own keys) and derived from `github.repository_owner` alone, so
  it's one stable prefix per org across every repo/template instance
  that org owns, rather than a per-repo namespace to look up each time.

## Do

- Give `release.yml` and `template-sync.yml` `contents: write` and
  nothing broader (`template-sync.yml` also needs `pull-requests:
  write`, for nothing else); leave `checks.yml` at `contents: read`.

## Don't

- Add a third way to cut a release — extend `release.yml`'s inputs
  instead, so there's one path and one changelog source.
