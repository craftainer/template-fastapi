# Extend template-base's release contract with an arch matrix, then tag v1.2.0

## Status

Draft

Step 4 of the sequence in
[`2026-09-template-base-extraction.md`](2026-09-template-base-extraction.md)'s
"Execution" section. Repo: **craftainer/template-base**.
Depends on: `2026-09-base-extension-points.md` merged.
`v1.1.0` is already taken: template-base cut it on 2026-09-24 for the
local-manifest feature. This work is the next minor, `v1.2.0`.

## Goal

template-base's `release.yml` is one job running `make build/sbom/
release-assets/publish`. template-fastapi's release does three things
that shape can't express:
- it builds natively on an amd64 and an arm64 runner, with no QEMU;
- it combines the per-arch registry tags into one multi-arch manifest
  list;
- it runs the test suite inside the devcontainer, with the backing
  services up, to attach `coverage.xml`.

Decision (recorded in the umbrella plan): extend the contract in
template-base so it covers these, keep `release.yml` `replace` tier, and
make a single-arch no-op still the default.

## The contract (exact; plan 5 implements it for template-fastapi)

| Target | Runs | Where | Env available |
|---|---|---|---|
| `release-arches` | once, first | host runner | — ; must print a JSON array on stdout, e.g. `["amd64"]` |
| `build`, `sbom`, `release-assets`, `publish` | once **per arch**, in that order | host runner for that arch | `RELEASE_VERSION`, `RELEASE_TAG`, `RELEASE_ARCH`, `OCI_REGISTRY`, `OCI_IMAGE_NAME`, `OCI_REGISTRY_USERNAME`, `OCI_REGISTRY_PASSWORD`, all `GITHUB_*` |
| `release-check` | once, after all arches | **inside the devcontainer** (`devcontainers/ci`), stack up | `RELEASE_VERSION`, `RELEASE_TAG` |
| `finalize` | once, after `release-check` | host runner | same as per-arch minus `RELEASE_ARCH` |

`dist/` rules: each arch leg's `dist/` is uploaded as artifact
`release-assets-<arch>`. The final job downloads all of them into one
`dist/`, so **per-arch file names must include the arch**.
`release-check` and `finalize` may add more files to `dist/`. Every
file in `dist/` at the end is attached to the GitHub release.

## Approach

### 1. `Makefile`

Add `release-arches` (prints `["amd64"]`), `release-check` and
`finalize` as documented no-ops, in the same style as the existing
targets. Add them to `.PHONY`. `release-arches` must print *only* the
JSON: use `@echo '["amd64"]'`.

### 2. `.github/workflows/release.yml`

Rewrite the jobs. Keep the header comment (update it), the `on:`
inputs, and `permissions:` unchanged.

- **`version`**: as today, plus one step after checkout:
  `echo "arches=$(make -s release-arches)" >> "$GITHUB_OUTPUT"`, and
  an `arches` output on the job.
- **`build`** (`needs: version`), with
  `strategy: { fail-fast: false, matrix: { arch: ${{ fromJSON(needs.version.outputs.arches) }} } }`
  and
  `runs-on: ${{ matrix.arch == 'arm64' && (vars.CI_RUNNER_ARM64 || 'ubuntu-24.04-arm') || (vars.CI_RUNNER_AMD64 || 'ubuntu-24.04') }}`
  (keep the `# renovate: datasource=github-runners depName=ubuntu`
  comment above it). Job `env:` holds all the per-arch variables from
  the contract table. `OCI_*` come from `vars.`/`secrets.` exactly as
  template-fastapi's current `release.yml` reads them. Steps:
  1. checkout (`actions/checkout`, same pin as today);
  2. `docker/setup-buildx-action` (same pin as today);
  3. `crazy-max/ghaction-github-runtime`, pinned to its latest exact
     release. Look the version up on its GitHub releases page; don't
     guess. This exposes `ACTIONS_RUNTIME_TOKEN`/`ACTIONS_RESULTS_URL`
     to `run:` steps so a `make build` can use `--cache-to type=gha`.
     Add a one-line comment saying so.
  4. `make build`, then `make sbom`, `make release-assets`, `make publish` (one step each);
  5. `actions/upload-artifact` (the exact version plan 1 settled on),
     `name: release-assets-${{ matrix.arch }}`, `path: dist/`,
     `if-no-files-found: ignore`.
- **`release`** (`needs: [version, build]`, the single-runner expression
  the file already uses for `version`):
  1. checkout;
  2. `actions/download-artifact` (plan 1's version),
     `pattern: release-assets-*`, `merge-multiple: true`, `path: dist/`;
  3. `Set compose project name` — copy the step verbatim from
     `checks.yml`;
  4. `devcontainers/ci` (same pin as `checks.yml`), with
     `runCmd: make release-check` and `env:` passing `RELEASE_VERSION`
     and `RELEASE_TAG`. Check `checks.yml` for how it passes env into
     the container, and use the same mechanism;
  5. `Tear down devcontainer stack` — copy verbatim from `checks.yml`,
     keeping `if: always()`;
  6. `make finalize`, with the same `env:` as `build` minus `RELEASE_ARCH`;
  7. the existing `Create GitHub release` step, unchanged (it already
     globs `dist/*`).

### 3. Docs

- `docs/TEMPLATE.md` "Release: a Makefile contract": replace the target
  list with the contract table and the `dist/` rules above. Add one
  paragraph saying the arch legs run natively (arm64 on
  `ubuntu-24.04-arm`, overridable with `CI_RUNNER_ARM64` /
  `CI_RUNNER_AMD64`), not under QEMU.
- `.github/workflows/README.md`: update the `release.yml` bullet to
  match, and document the `OCI_*` variables/secrets and
  `CI_RUNNER_AMD64` / `CI_RUNNER_ARM64`. Copy the wording from
  template-fastapi's `.github/workflows/README.md`, whose sections on
  these already exist.

## Verify

Show the output of each:

    make -s release-arches | python3 -c 'import json,sys; assert json.load(sys.stdin)==["amd64"]; print("OK")'
    make build sbom release-assets publish release-check finalize   # every target exits 0
    prek run --all-files --hook-stage manual                        # passes

Then run the real workflow once on template-base: Actions → Release →
`release_type: alpha`, `bump: minor`. It must finish green. Its
`release-check` step exercises `devcontainers/ci` against base's own
devcontainer. Delete that alpha release and its tag afterwards
(`gh release delete v1.2.0-alpha.1 --cleanup-tag --yes`, or the
equivalent in the web UI).

## Tag

Once plans 2, 3 and 4 are all merged and the alpha run above passed:
Actions → Release → `release_type: full`, `bump: minor`. Expected tag:
`v1.2.0`. If the computed tag is anything else, stop and ask. Plan 6
bootstraps against it.

## Done when

`v1.2.0` exists on template-base, and its release job was green.
