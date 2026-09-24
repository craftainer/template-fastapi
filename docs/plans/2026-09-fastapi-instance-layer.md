# Build template-fastapi's instance-owned layer for template-base's hooks

## Status

Draft

Step 5 of the sequence in
[`2026-09-template-base-extraction.md`](2026-09-template-base-extraction.md)'s
"Execution" section. Repo: **craftainer/template-fastapi** (this one).
Can run **in parallel with plans 2–4**: it only adds new files (plus two
small edits listed in step 6) that nothing references until plan 6
wires them in. The hook names come from the "Fixed names" table in
`2026-09-base-extension-points.md` and the contract table in
`2026-09-base-release-matrix.md`. Treat both tables as given, even if
those plans haven't merged yet.

## Goal

Move everything FastAPI-specific in today's base-owned files into files
template-fastapi owns: extra develop tooling, post-create steps, the
backing-service stack, the runtime image, and release logic. After
that, plan 6's sync can overwrite the base-owned files without losing
anything.

## Approach

Branch: `feat/instance-layer`. For each new file, copy the explanatory
comments from the file it came from, the same way the source did. This
repo comments heavily.

### 1. `scripts/develop.d/`

Diff `scripts/develop.sh` against template-base's `scripts/develop.sh`
(`git show` it from a clone of template-base `main`). Everything
template-fastapi's version installs that base's doesn't goes into a
`develop.d` script. At the time of writing that is:

| New file | Contents moved from `scripts/develop.sh` |
|---|---|
| `scripts/develop.d/10-apt.sh` | `apt-get install` of `libpq-dev postgresql-client redis-tools` (base already installs `xz-utils`) |
| `scripts/develop.d/20-pyright.sh` | the `uv tool install pyright` block + symlinks |
| `scripts/develop.d/30-rustfs-cli.sh` | the rustfs-cli `.deb` download/verify/install block |
| `scripts/develop.d/40-kcadm.sh` | the `kcadm` wrapper heredoc block |

If the diff shows any other fastapi-only block, give it its own `NN-`
script and list it in the PR. Python, uv, Node, Claude Code, snip and
prek are already installed by base's `develop.sh` — don't duplicate them.

**Version pins.** `PYRIGHT_VERSION` and `RUSTFS_CLI_VERSION` are
`Dockerfile` ARGs today. Move each into its script, using this exact
two-line shape (Renovate's new custom manager matches it):

    # renovate: datasource=pypi depName=pyright
    PYRIGHT_VERSION=1.1.414

Copy the `datasource=`/`depName=` values and the version from the
current `Dockerfile` ARG comments exactly. Each script starts with
`#!/usr/bin/env bash` and `set -euo pipefail`.

### 2. `scripts/post-create.d/`

Today's `postCreateCommand` is `git config ... && uv sync --extra dev
&& uv run prek install && uv run alembic upgrade head`. Base's
`post-create.sh` already does the `git config` and (standalone)
`prek install` parts. Create:

- `scripts/post-create.d/10-uv-sync.sh` → `uv sync --extra dev`
- `scripts/post-create.d/20-migrate.sh` → `uv run alembic upgrade head`

### 3. `.devcontainer/compose.instance.yml`

In base's `.devcontainer/compose.yml` the dev service is `app`; here it
is `api`. Plan 6 renames the service. This file already targets `app`:

- `include:` — the six `./stack/*/compose.yml` entries from the top of
  the current `.devcontainer/compose.yml`, in the same order.
- `services.app` — everything the current `api` service has that base's
  `app` service doesn't: `env_file`, `depends_on` (with its
  `condition: service_healthy` entries), and any other keys the diff
  shows. Keep their comments.
- `services.app.environment` — the ENV values the current `Dockerfile`
  `develop` stage sets that base's doesn't:

      PYTHONUNBUFFERED: "1"
      PYTHONDONTWRITEBYTECODE: "1"
      UV_LINK_MODE: copy
      UV_PROJECT_ENVIRONMENT: /home/vscode/.venv
      UV_PYTHON: /usr/local/bin/python3

  `UV_PYTHON` points at the symlink base's `develop.sh` creates for its
  pinned uv-installed CPython. That way no second copy of the version
  number exists.

Verify against base's compose file, **not** this repo's current one:

    git -C <template-base clone> show main:.devcontainer/compose.yml > .devcontainer/compose.base-check.yml
    docker compose -f .devcontainer/compose.base-check.yml -f .devcontainer/compose.instance.yml config >/dev/null && echo OK
    rm .devcontainer/compose.base-check.yml

This only renders the config and doesn't start anything. Don't `up` a
second stack (CLAUDE.md: use the devcontainer's own services).

### 4. `app.Dockerfile` + `app.Dockerfile.dockerignore`

- `app.Dockerfile`: the `builder` and `runner` stages from the current
  `Dockerfile` (the `# builder` banner through the end of the file).
  Also copy the `ARG`s they need from the top of `Dockerfile` —
  `PYTHON_VERSION`, `DEBIAN_VERSION`, `UV_VERSION`, `APP_UID`,
  `SSL_CERT_FILE`, `SSL_CERT_DIR` — with their `# renovate:` comments.
  Rewrite the header comment: "Runtime image (builder → runner);
  the devcontainer image is the base-owned `Dockerfile`'s `develop`
  stage."
- `app.Dockerfile.dockerignore`: the full current `.dockerignore`.
  BuildKit uses a `<name>.dockerignore` *instead of* `.dockerignore`
  when building `-f <name>`, so it needs all the entries, not just the
  7 fastapi additions.
- Don't delete anything from `Dockerfile` in this plan; plan 6's sync
  replaces it.

**Version drift guard.** `PYTHON_VERSION` and `DEBIAN_VERSION` now live
in both `Dockerfile` (base-owned) and `app.Dockerfile`. Add
`scripts/check-dockerfile-versions.sh`. It extracts
`ARG PYTHON_VERSION=` and `ARG DEBIAN_VERSION=` from both files, prints
a clear message and exits 1 on any mismatch. Register it in
`.pre-commit-config.yaml` as a `repo: local` hook with
`language: system`, `files: ^(app\.)?Dockerfile$`,
`pass_filenames: false`, and stages matching the other local hooks.
Copy the shape of the existing `template-sync-manifest` local hook.

### 5. `Makefile` — the release contract

Implement the contract table from `2026-09-base-release-matrix.md`.
This reproduces today's `release.yml` behavior: native per-arch OCI
tarball + SPDX SBOM, optional per-arch registry push, a manifest list,
and `coverage.xml` from a devcontainer test run. Starting point below.
Recipe lines must be indented with a **TAB**.

```make
# template-fastapi's implementation of template-base's release contract
# (docs/TEMPLATE.md, "Release: a Makefile contract"). release.yml sets
# RELEASE_VERSION / RELEASE_TAG / RELEASE_ARCH / OCI_* -- see there.

.PHONY: release-arches build sbom release-assets publish release-check finalize

ARCHES := amd64 arm64
REPO := $(or $(GITHUB_REPOSITORY),craftainer/template-fastapi)
OWNER := $(firstword $(subst /, ,$(REPO)))
IMAGE := $(notdir $(REPO))
ASSET := dist/$(IMAGE)-$(RELEASE_VERSION)-$(RELEASE_ARCH)
RELEASE_URL := https://github.com/$(REPO)/releases/download/$(RELEASE_TAG)
OCI_NAME := $(shell printf '%s' '$(or $(OCI_IMAGE_NAME),$(REPO))' | tr '[:upper:]' '[:lower:]')

# renovate: datasource=docker depName=anchore/syft
SYFT_VERSION := vX.Y.Z

# Only set in CI, by crazy-max/ghaction-github-runtime in release.yml.
ifdef ACTIONS_RUNTIME_TOKEN
CACHE := --cache-from type=gha,scope=$(RELEASE_ARCH) --cache-to type=gha,mode=max,scope=$(RELEASE_ARCH)
endif

# Same label set docker/metadata-action produced in the old release.yml.
# `created` is the commit time so build and publish produce identical
# labels (and therefore the same image) in separate make invocations.
LABELS := \
	--label org.opencontainers.image.title=$(IMAGE) \
	--label org.opencontainers.image.source=https://github.com/$(REPO) \
	--label org.opencontainers.image.url=https://github.com/$(REPO) \
	--label org.opencontainers.image.version=$(RELEASE_VERSION) \
	--label org.opencontainers.image.revision=$(shell git rev-parse HEAD) \
	--label org.opencontainers.image.created=$(shell git log -1 --format=%cI) \
	--label org.opencontainers.image.licenses=GPL-3.0 \
	--label io.github.$(OWNER).sbom=$(RELEASE_URL)/$(IMAGE)-$(RELEASE_VERSION)-$(RELEASE_ARCH).spdx.json \
	--label io.github.$(OWNER).coverage-report=$(RELEASE_URL)/coverage.xml

BUILD := docker buildx build -f app.Dockerfile --target runner \
	--platform linux/$(RELEASE_ARCH) $(LABELS) $(CACHE)

release-arches:
	@python3 -c 'import json,sys; print(json.dumps(sys.argv[1:]))' $(ARCHES)

build:
	mkdir -p dist
	$(BUILD) --output type=oci,dest=$(ASSET).tar .

sbom:
	docker run --rm -v "$(CURDIR)/dist:/dist" anchore/syft:$(SYFT_VERSION) \
		oci-archive:/$(ASSET).tar -o spdx-json=/$(ASSET).spdx.json

release-assets:
	test -f $(ASSET).tar && test -f $(ASSET).spdx.json

publish:
ifeq ($(OCI_REGISTRY),)
	@echo "OCI_REGISTRY not set -- skipping publish."
else
	@printf '%s' "$$OCI_REGISTRY_PASSWORD" | docker login "$(OCI_REGISTRY)" -u "$$OCI_REGISTRY_USERNAME" --password-stdin
	$(BUILD) --push -t $(OCI_REGISTRY)/$(OCI_NAME):$(RELEASE_VERSION)-$(RELEASE_ARCH) .
endif

release-check:
	mkdir -p dist
	uv run pytest --cov-report=xml:dist/coverage.xml

finalize:
ifeq ($(OCI_REGISTRY),)
	@echo "OCI_REGISTRY not set -- no manifest list to create."
else
	@printf '%s' "$$OCI_REGISTRY_PASSWORD" | docker login "$(OCI_REGISTRY)" -u "$$OCI_REGISTRY_USERNAME" --password-stdin
	docker buildx imagetools create --tag $(OCI_REGISTRY)/$(OCI_NAME):$(RELEASE_VERSION) \
		$(foreach a,$(ARCHES),$(OCI_REGISTRY)/$(OCI_NAME):$(RELEASE_VERSION)-$(a))
endif
```

- Replace `vX.Y.Z` with the current `anchore/syft` release. Check that
  the tag format on Docker Hub matches (with or without the `v`).
- Add a Renovate custom manager for `Makefile` to
  `.github/renovate.json`. It matches
  `# renovate: datasource=... depName=...` followed on the next line by
  `NAME_VERSION := value`, using the same shape as the existing
  Dockerfile manager. (After plan 3, `renovate.json` is `merge` tier,
  so this addition survives syncs.)
- Confirm `dist/` is gitignored: `git check-ignore -q dist/x && echo ignored`.
  If not, add `dist/` to `.gitignore`.

### 6. Edits to existing files

- Root `compose.yml` (the smoke/perf stack, a separate project from the
  devcontainer): point its `runner` build at the new file
  (`dockerfile: app.Dockerfile`, keep `target: runner`). Then
  `grep -rn "target: runner\|--target runner" .github/ compose.yml`.
  Update every other hit to build from `app.Dockerfile` too (e.g.
  `smoke.yml`). Do **not** rename the smoke stack's `api` service. It
  is not the devcontainer service.
- `.github/template-sync-manifest.yml` (this repo's own, for its own
  downstream instances): classify every new file. Rule: each new file
  goes in the same tier as the file its content came from.
  - `app.Dockerfile` and `app.Dockerfile.dockerignore` take
    `Dockerfile`'s tier.
  - `scripts/develop.d/*` and `scripts/post-create.d/*` take `scripts/`'s tier.
  - `scripts/check-dockerfile-versions.sh` takes `scripts/`'s tier.
  - `.devcontainer/compose.instance.yml` takes `.devcontainer/`'s tier.
  - `Makefile` takes `.github/workflows/release.yml`'s tier.

  If a directory glob already covers the file, add nothing.

## Verify

Show the output of each:

    uv run prek run --all-files --hook-stage manual     # passes, incl. the new version-drift hook and the manifest check
    make -s release-arches                              # prints ["amd64", "arm64"]
    export RELEASE_VERSION=0.0.0-local RELEASE_TAG=v0.0.0-local RELEASE_ARCH=$(dpkg --print-architecture)
    make build sbom release-assets publish              # dist/ has the .tar and .spdx.json; publish prints "skipping"
    make release-check                                  # inside this devcontainer (the stack is up): tests pass, dist/coverage.xml exists
    make finalize                                       # prints "no manifest list"
    docker load --input dist/template-fastapi-0.0.0-local-$RELEASE_ARCH.tar && \
      docker inspect --format '{{json .Config.Labels}}' <loaded image>   # the labels above are present
    rm -rf dist

Also run the version-drift hook negatively. Temporarily edit
`app.Dockerfile`'s `PYTHON_VERSION`, run
`uv run prek run check-dockerfile-versions --all-files`, and show that
it fails. Then revert the edit.

The `develop.d`/`post-create.d` scripts can only be tested for real
once plan 6 wires them in. Here, run `bash -n` on each (syntax check)
and show the output.

## Done when

The PR (`feat: move fastapi-specific build/dev layers into
instance-owned files`) is merged. `release.yml`, `Dockerfile` and
`.devcontainer/` are behaviorally unchanged on `main`.
