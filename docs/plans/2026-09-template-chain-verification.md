# Verify the template-base → template-fastapi → instance sync chain

## Status

Draft

Step 7 of the sequence in
[`2026-09-template-base-extraction.md`](2026-09-template-base-extraction.md)'s
"Execution" section. Repos: template-base, template-fastapi, and
throwaway repos created for this plan. Depends on: plan 6 merged.

## Goal

Show that each hop of the chain works end to end, and that the
extraction didn't break repos already created from template-fastapi.
This covers §5 of the umbrella plan, as concrete checks.

## Approach

Record each check's result (the PR link or the command output) in a
comment on this plan's tracking PR, or in the PR that deletes these
plans. Any failure: **stop and report it**. Don't patch around it in
the throwaway repos.

### A. Base → fastapi

1. In template-base, change one line of `CLAUDE.md` (a real wording
   fix, not a dummy edit). Merge it, then release a patch
   (`release_type: full`, `bump: patch`, which should give `v1.2.1`).
2. In template-fastapi, run Actions → Template sync with no inputs.
3. Pass: the PR changes exactly `CLAUDE.md` and
   `.github/template-sync-state.json` (the recorded tag). Merge it.

### B. Fastapi → its existing instances (the regression check)

1. Find a repo whose `.github/template-sync-state.json` points at
   `craftainer/template-fastapi`. Ask the user which one to use. If
   none exists, create one from template-fastapi's template **as it was
   before plan 6**. That means the last tag before plan 6's merge:
   create the repo, then reset it to that tag, and bootstrap its state
   file at that tag.
2. Cut a template-fastapi patch release, so there's something to sync.
3. Run that instance's Template sync with no inputs. Pass, all three:
   - It syncs from `craftainer/template-fastapi`, not template-base.
     Its state file is unchanged apart from the tag.
   - Its own `.github/template-sync-manifest.yml` is updated from
     template-fastapi's manifest (fastapi-tier rules), not base's.
     Whatever tier fastapi's manifest gives that path, the instance's
     own entries survive.
   - The devcontainer builds and `prek run --all-files --hook-stage
     manual` passes on the PR branch. The user rebuilds; ask them.

### C. Base standalone — two opposite shapes

Create two throwaway repos from template-base `v1.2.x`:

1. **Infra-only** (e.g. `tmp-base-infra`):
   - Add `scripts/develop.d/10-tofu.sh`. It installs a pinned OpenTofu
     release binary, with checksum verification like the existing
     scripts, and the `# renovate:` pin shape.
   - Add a `tflint` or `tofu fmt -check` local hook to
     `.pre-commit-config.yaml`.
   - Leave the `Makefile` as base's no-ops.
   - Pass: the devcontainer builds, `tofu version` works in it, and
     `prek run --all-files --hook-stage manual` passes. A
     `release_type: alpha` run creates a release with no assets and
     exits green.
2. **Language port** (e.g. `tmp-base-go`):
   - Add a Go "hello" HTTP service, and
     `scripts/develop.d/10-go.sh` to install Go.
   - Add `app.Dockerfile` with `builder`/`runner` stages.
   - Add a `Makefile` implementing `build`/`sbom`/`release-assets`,
     modelled on template-fastapi's `Makefile`, with
     `ARCHES := amd64 arm64`.
   - Pass: the devcontainer builds, `prek` passes, and an alpha release
     attaches one `.tar` and one `.spdx.json` **per arch**.

   In both repos, list the repo's own files (`*.tf`, `cmd/`, `go.mod`,
   `app.Dockerfile`, ...) under `ignore:` in
   `.github/template-sync-manifest.local.yml`. Don't edit the manifest
   itself. This is the local-manifest path base `v1.1.0` added for
   ordinary instances, so it gets exercised here. Pass: the
   `template-sync-manifest` hook passes.
3. In each throwaway repo, bootstrap Template sync against
   `craftainer/template-base`. Pass: the bootstrap PR contains only
   the state file.

Delete all throwaway repos and alpha releases/tags afterwards, after
asking the user for confirmation, since deleting repos is irreversible.

## Done when

A, B and C all pass. Then do the umbrella plan's "Finish" step.
