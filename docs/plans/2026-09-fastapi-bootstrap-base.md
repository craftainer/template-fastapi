# Bootstrap template-fastapi onto template-base v1.2.0

## Status

Draft

Step 6 of the sequence in
[`2026-09-template-base-extraction.md`](2026-09-template-base-extraction.md)'s
"Execution" section. Repo: **craftainer/template-fastapi** (this one).
Depends on: template-base `v1.2.0` tagged (plan 4) **and**
`2026-09-fastapi-instance-layer.md` merged (plan 5).

## Goal

Make template-fastapi a sync instance of template-base, so generic
scaffolding fixes flow base → fastapi → fastapi's own instances. The
first sync PR is also where the base-owned files get replaced and the
instance-owned layer from plan 5 gets wired in. It has to land as **one
PR**: any half-merged state leaves the devcontainer broken.

## Approach

### 1. Bootstrap the state file

Actions → **Template sync** → Run workflow, with
`template_repo: craftainer/template-base`, `initial_sync_tag: v1.2.0`.
This opens a PR that adds only `.github/template-sync-state.json`. If
it changes any other file, stop and ask. Merge it.

### 2. Open the first real sync

Actions → **Template sync** → Run workflow with no inputs. It opens a
sync PR from template-base `v1.2.0`. Check out that PR's branch locally.
Do everything below **on that branch**, as extra commits.

### 3. Safety checks before editing anything

Run each and show the output:

    git diff --name-only origin/main... | grep -E '^(src|tests|alembic|\.devcontainer/stack)/|^(pyproject\.toml|uv\.lock|compose\.yml|Makefile|app\.Dockerfile)$'
        # must print nothing: the sync must never touch fastapi-only paths
    git diff origin/main... -- .github/template-sync-manifest.yml | grep '^-[^-]'
        # must print nothing: the manifest is merge tier, so base's changes may add lines, but none of fastapi's own entries may be removed
    git diff origin/main... -- .github/workflows/moderate-bug-fix.yml | grep '^[-+].*\(contents\|issues\|pull-requests\): write'
        # must print nothing: no permission escalation

If any check prints something, **stop**. Don't fix it here: the bug is
in template-base (plan 2 or 3). Close the PR, fix template-base, tag a
patch release, and restart from step 2.

### 4. Reconcile

Expected `replace` changes. **Accept** these as-is, no edits:
- `Dockerfile` — becomes `develop`-only. The runtime stages live in
  `app.Dockerfile` (plan 5).
- `scripts/develop.sh` — the fastapi extras live in `scripts/develop.d/`.
- `scripts/post-create.sh`, `scripts/develop.d/README.md`,
  `scripts/post-create.d/README.md` — new.
- `.devcontainer/compose.yml` — the stack `include:` and `api`
  settings now live in `compose.instance.yml`.
- `.github/workflows/release.yml` — the matrix contract, driven by
  plan 5's `Makefile`.
- `.github/workflows/checks.yml`, `.claude/hooks/self-check.sh`,
  `CLAUDE.md`, `.github/PULL_REQUEST_TEMPLATE.md`,
  the moderation workflows and prompts — generic wording, bare `prek`.

`merge`-tier conflicts. Resolve each one. The rule: **keep
template-fastapi's FastAPI/Python/stack-specific content, and take
template-base's wording and structure everywhere else.** Specifics:
- `.devcontainer/devcontainer.json`:
  - Take base's `dockerComposeFile` array, `"service": "app"` and
    `postCreateCommand` (`bash /workspace/scripts/post-create.sh`).
  - Keep fastapi's `name`, `forwardPorts`, `portsAttributes`, and its
    extra `extensions` and `settings` entries.
- `.pre-commit-config.yaml`: keep every fastapi hook (ruff, mypy,
  import-linter, pytest, pytest-e2e, uv-lock-check, pip-audit,
  check-dockerfile-versions). Also take base's changes to the shared
  hooks, including the `devcontainer-lock` hook added in base `v1.1.0`.
- `.github/template-sync-manifest.yml` (`merge` tier, as of plan 3):
  keep every fastapi classification. Where base adds an entry for a path
  fastapi also has, put it in the tier fastapi's own downstream
  instances should get. Add `.github/template-sync-manifest.local.yml`
  to `ignore`, so fastapi's instances can use the local file too. Base
  `v1.1.0`'s checker supports it, and this sync delivers that checker.
- `.github/renovate.json`: keep both of fastapi's custom managers (the
  Playwright one and the Makefile one from plan 5), plus base's
  `develop.d` manager.
- `.mcp.json`, `.claude/settings.json`: keep fastapi's servers,
  permissions and plugins.
- `.gitignore`, `.dockerignore`: take the union of both sides.
- READMEs and `docs/TEMPLATE.md`: keep fastapi's sections on the stack,
  smoke/perf and the Python checks. Add base's new "Instance extension
  points" section and its release contract text.

Commit the resolution as `chore(template-sync): resolve merge-tier
conflicts`.

### 5. Rename the devcontainer service `api` → `app`

Base names the dev service `app`. Update **only** these references to
the devcontainer service:
- `tests/e2e/conftest.py` — the `http://api:` host in the base-URL helper
- `tests/e2e/README.md` — `http://api:8000`
- `.devcontainer/stack/selenium/README.md` — `http://api:8000`
- anything else that
  `grep -rnE "//api[:/]|exec api|service.*\bapi\b" --exclude-dir=.git .`
  finds, **except** the matches listed under "Do not rename"

Also check each `.devcontainer/stack/*/compose.yml` and `*.env` for
`api` used as a hostname, e.g. in an `E2E_BASE_URL` value, and rename
those too.

Do **not** rename:
- the Keycloak client id `"api"` (`realm-export.json`,
  `src/app/config.py`, `tests/unit/test_config.py`). It's an OAuth
  audience, not a hostname.
- the root `compose.yml`'s smoke-stack `api` service. That's a separate
  compose project.

Commit as `refactor(devcontainer): rename dev service api -> app to
match template-base`.

### 6. Clean up what the sync orphaned

- `scripts/builder*.sh` and `scripts/runner*.sh` are still used by
  `app.Dockerfile`. Keep them.
- `.dockerignore` is now used only by the `develop` build. It may keep
  the union from step 4.
- Search for stale docs:
  `grep -rn "uv run prek" --exclude-dir=.git .`. Anything left outside
  `docs/plans/` should become `prek` (prek is now a standalone tool).
- Run `python3 .github/scripts/check_devcontainer_lock.py` (new from
  base). If it fails, regenerate the lockfile with
  `npx @devcontainers/cli upgrade --workspace-folder .` and commit it.
- Set the repository variable `MODERATION_EXTRA_TOOLS` to
  `Bash(uv run *)`, so the moderation jobs keep the `uv run` access
  they have today. You can't do this yourself: in the PR description,
  ask the user to set it in the repo settings.

## Verify

Everything here needs the new devcontainer, and **only the user can
rebuild it** (CLAUDE.md). Push the branch, then ask the user to
"Rebuild Container" from this branch and report back. After they
confirm, run each of these inside the rebuilt container and show the
output:

    command -v prek pyright rc kcadm psql redis-cli    # all resolve (develop.d ran)
    python3 --version                                  # matches ARG PYTHON_VERSION in Dockerfile
    ls /home/vscode/.venv/bin/python                   # post-create.d/10-uv-sync.sh ran
    prek run --all-files --hook-stage manual           # passes (ruff, mypy, pytest, e2e, ...)

CI on the PR must be green: `checks.yml` on both arches, and `smoke.yml`
building from `app.Dockerfile`.

Release: after merging, run Actions → Release with `release_type:
alpha`, `bump: patch`. Confirm the release has these attached:
- `template-fastapi-<v>-amd64.tar` and `.spdx.json`
- `template-fastapi-<v>-arm64.tar` and `.spdx.json`
- `coverage.xml`

This is the same asset set as before this work. Then delete that alpha
release and its tag. If `OCI_REGISTRY` is configured, also confirm that
`docker buildx imagetools inspect <registry>/<name>:<v>` lists both
arches.

## Done when

The sync PR is merged, the rebuilt devcontainer passes the checks
above, and the alpha release produced the same asset set as before.
