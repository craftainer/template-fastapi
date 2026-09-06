# Add default OCI labels, SBOM reference, and coverage reference to releases

## Status

Draft

## Goal

`release.yml` currently ships an unlabeled OCI image (tarball + optional
registry push) with nothing pointing back at what's inside it. Add a
standard set of `org.opencontainers.image.*` labels, plus a
discoverable link from the image to an SBOM and to the test-coverage
report for the exact commit it was built from — both attached to the
GitHub release, not folded into the image so the pattern stays useful
regardless of what language/stack the app is written in.

## Approach

### 1. Default OCI labels via `docker/metadata-action`

- Add `docker/metadata-action` (pin a version, matching the pinning
  style of the other `docker/*` actions already in `release.yml`) as a
  step before the two `build-push-action` calls. It's generic Docker
  tooling that reads git/GitHub context, not tied to Python, so this
  satisfies "language agnostic" on its own.
- Feed it `images:` (the tarball tag / `${{ vars.OCI_REGISTRY }}/...`
  name), and let it derive `org.opencontainers.image.title`,
  `.description`, `.url`, `.source`, `.revision` (`github.sha`),
  `.created` (build timestamp), and `.version` /
  `.licenses` (from the repo's `LICENSE` file, if `metadata-action`
  can detect it — otherwise set explicitly).
- Pass `steps.meta.outputs.labels` into `labels:` on **both**
  `build-push-action` invocations (tarball export and registry push)
  so the two copies of the image carry identical labels.

### 2. SBOM: generate, attach to the release, reference from the image

- After the tarball build step, run `anchore/sbom-action` (wraps
  Syft) against the built image reference, producing an SPDX-JSON
  SBOM. Syft introspects installed packages/binaries inside the image
  layers regardless of the app's language, so this step doesn't
  change if the template's stack changes.
- Add the SBOM file to the same `gh release create` file list that
  already attaches the OCI tarball, so it lands as a second
  downloadable release asset.
- GitHub's release-asset download URL is deterministic
  (`https://github.com/<owner>/<repo>/releases/download/<tag>/<asset-name>`)
  and the tag is already computed early in the job (`compute_next_version.py`
  runs first) — so build that URL *before* the image build step and
  pass it into `docker/metadata-action`'s extra `labels:` input (or
  append it directly to `steps.meta.outputs.labels`) as a custom,
  reverse-DNS-namespaced annotation, e.g.
  `io.github.${{ github.repository_owner }}.sbom=<url>` (the
  `org.opencontainers.image.*` namespace is reserved for the spec's own
  keys, so a custom pointer needs its own namespace). The namespace is
  derived from `github.repository_owner` alone, at run time — not the
  repo name too, and not hardcoded. Keying it to the org only, and
  nothing more specific, keeps it a single well-known prefix per org
  across every repo/template instance that org owns, rather than a
  different one per repo that consumers would have to look up per
  image. This makes the image self-describing: anyone with just the
  image can find its SBOM.

### 3. Test coverage: generate, attach to the release, reference from the image

- `release.yml` doesn't currently run the test suite at all (it
  trusts `checks.yml` already gated the commit). To attach a coverage
  report for the *exact* artifact being released, add a step — reusing
  the same `devcontainers/ci` + `uv run pytest` pattern as
  `checks.yml` — that runs the suite with `--cov-report=xml` (in
  addition to the `--cov-report=term-missing` already set in
  `pyproject.toml`'s `addopts`; pass the extra flag on the CLI rather
  than changing the shared default) to produce `coverage.xml`.
- Attach `coverage.xml` to the GitHub release the same way as the
  SBOM. No `htmlcov/` — one machine-readable asset is enough, and
  skips the extra zip step.
- Add a second custom label,
  `io.github.${{ github.repository_owner }}.coverage-report=<url>`,
  computed the same way and at the same point as the SBOM URL, before
  the image build step.
- Note: unlike the SBOM step, this one is **not** language-agnostic —
  it's `uv run pytest --cov-report=xml`, i.e. Python's `coverage.py`.
  The Cobertura-style XML *format* is a cross-language convention
  other ecosystems' coverage tools can also emit, but the generation
  step itself is tied to this repo's current Python toolchain and
  would need rewriting if the stack ever changed language. Accepting
  this as a known, scoped limitation rather than building an
  abstraction layer for a hypothetical future stack.

### 4. Ordering within the job

Because labels are baked in at build time but the release (and its
real download URLs) is only created afterward, the job needs this
order: compute version/tag → compute predictable SBOM/coverage asset
URLs → `docker/metadata-action` (including the two custom URL labels)
→ build tarball (with labels) → generate SBOM from the built image →
run tests to produce `coverage.xml` → registry push (with same
labels) → `gh release create` with tarball + SBOM + `coverage.xml` as
assets.

### 5. Documentation

- Update `.github/workflows/README.md`'s `release.yml` bullet and "OCI
  registry" section to describe the label set and the SBOM/coverage
  assets.
- If the custom label namespace and SBOM tool choice should be
  recorded as a decision (per `CLAUDE.md`'s ADR guidance), add a short
  ADR in `docs/adrs/` once the open questions below are settled;
  otherwise the workflow file's own comments are enough.

## Decisions

- **SBOM format**: SPDX-JSON. Both SPDX and CycloneDX are themselves
  language-neutral formats, and Syft (the tool `anchore/sbom-action`
  wraps) generates from the built image's layers regardless of what
  language produced them — SPDX-JSON is just Syft's/`sbom-action`'s
  broadly-supported default, no ecosystem-specific option needed.
- **Custom label namespace**: derived at run time from
  `github.repository_owner` only (not the repo name), not hardcoded —
  see "SBOM" and "coverage" sections above. One well-known prefix per
  org, stable across every repo/template instance that org owns,
  rather than a per-repo namespace consumers would need to look up
  each time. Keeps the template instantiation-agnostic.
- **Scope of labels**: only `release.yml`'s published image gets the
  `org.opencontainers.image.*` / custom labels. `checks.yml` and
  `smoke.yml` build images only to test them in CI and never publish
  or distribute them, so labeling those adds no value.

- **Coverage asset**: `coverage.xml` only, no `htmlcov/` — one
  machine-readable asset is sufficient and avoids an extra zip step.
