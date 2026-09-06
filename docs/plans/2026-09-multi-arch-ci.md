# Multi-arch CI: test and build for amd64 and arm64

## Status

Draft

## Goal

An arm64 devcontainer build/run was manually verified working end-to-end
on 2026-09-06 (stack images, `uv sync`, ruff/mypy/pytest/e2e, and the
`runner` image all pass natively on aarch64), but nothing in CI actually
proves this on an ongoing basis — `checks.yml`, `smoke.yml`, and
`release.yml` all only ever run on `ubuntu-latest` (amd64). This plan
makes arm64 a continuously-checked, continuously-shipped target instead
of a one-off manual verification, without changing local devcontainer
behavior (which already builds for whichever arch the host is on and
needs no change).

## Approach

1. **Devcontainer/local dev: no change.** `Dockerfile`'s `develop` stage
   already builds for the host's native arch via plain `docker build`/
   `docker compose build` — no `platforms:` pin exists today, so an
   arm64 host already gets an arm64 devcontainer for free. Deliberately
   do *not* pin it to `linux/amd64`: doing so would force arm64
   contributors through QEMU emulation for the one image they use
   constantly, for no verification benefit (CI is what needs to prove
   cross-arch correctness, not every contributor's inner loop).

2. **`checks.yml`: matrix the `prek` job over arch.** Add a
   `strategy.matrix` with two entries (amd64, arm64) and parameterize
   `runs-on` per entry — GitHub-hosted `ubuntu-24.04-arm` is a real
   (non-emulated) Linux arm64 runner, free on public repos and billed as
   ordinary Actions minutes on private ones. Everything else in the job
   (buildx setup, cache warm, `devcontainers/ci` invocation, teardown)
   stays the same, just running twice. Keep `${{ vars.CI_RUNNER }}` as
   an override *per arch* — split it into `CI_RUNNER_AMD64` /
   `CI_RUNNER_ARM64` (each still defaulting to the matching
   `ubuntu-*`/`ubuntu-*-arm` label) so self-hosted-runner users aren't
   forced onto GitHub's arm64 offering.

3. **`smoke.yml`: same matrix.** Build and run the `runner` stage's
   compose stack per arch and confirm `/health/live`/`/health/ready` on
   each — this is the check that would actually catch an arch-specific
   runtime break (e.g. a C-extension dependency missing an arm64 wheel),
   since `checks.yml`'s `pytest` run today uses `MODE=mock` in-process
   fakes for some paths rather than the built image.

4. **`release.yml`: build a real multi-arch image.** Add
   `docker/setup-qemu-action` (pinned to an exact version, alongside the
   existing `docker/setup-buildx-action` pin) and change both
   `docker/build-push-action` steps' `platforms:` to
   `linux/amd64,linux/arm64`. The registry push (`OCI_REGISTRY` step)
   becomes a genuine multi-arch manifest list with no further change.
   The GitHub-release tarball step needs a decision — see "Open
   questions" below — since a multi-platform OCI tarball isn't something
   plain `docker load` can consume.

5. **Docs.** Update `.github/workflows/README.md` (the `checks.yml`/
   `smoke.yml`/`release.yml` bullets, and the `CI_RUNNER` paragraph) and
   `docs/TEMPLATE.md`'s "Checks" section to describe the matrix and the
   split runner-override variables, per this repo's own rule that a
   convention about the repo belongs in that directory's `README.md`,
   not only in a plan file.

6. **Verify.** Push a branch/PR and confirm both matrix legs go green on
   `checks.yml` and `smoke.yml`; run `release.yml` once (an `alpha`
   release) and confirm the resulting image/tarball(s) actually contain
   both platforms (`docker buildx imagetools inspect` against the
   registry push; `tar`/`skopeo` inspection of the tarball).

## Open questions

- **GitHub-release tarball shape.** `docker/build-push-action` with
  `outputs: type=oci` and two platforms produces one OCI layout holding
  an image *index* over both — valid, but plain `docker load` can't load
  a multi-platform tarball directly (it wants a single platform). Pick
  one: (a) keep the attached tarball amd64-only (matching today) and
  make only the registry push multi-arch, (b) attach two tarballs to the
  release (`template-fastapi-<version>-amd64.tar` /
  `-arm64.tar`), or (c) attach the single multi-platform OCI tarball and
  document `docker buildx imagetools`/`skopeo` as the way to load it.
- **Runner cost/speed for `checks.yml`/`smoke.yml`.** Real
  `ubuntu-24.04-arm` runners are fast but only free on public repos;
  QEMU-emulated arm64 on a regular amd64 runner is free everywhere but
  meaningfully slower for a job that already runs the full
  `--hook-stage manual` suite. Confirm which this repository (or its
  instances) actually needs before implementing the matrix.
- **`CI_RUNNER` split.** Splitting into `CI_RUNNER_AMD64`/
  `CI_RUNNER_ARM64` is a breaking rename for anyone who already set the
  single `CI_RUNNER` variable for a self-hosted runner — confirm this
  template has no instances relying on the current name, or add a
  fallback.
