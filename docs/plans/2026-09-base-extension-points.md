# Add instance extension points and re-tier template-base's sync manifest

## Status

Draft

Step 3 of the sequence in
[`2026-09-template-base-extraction.md`](2026-09-template-base-extraction.md)'s
"Execution" section. Repo: **craftainer/template-base**.
Depends on: `2026-09-base-hardened-moderation.md` merged.
Written against template-base `v1.1.0` (`119d2d7`). That version
already has the `devcontainer-lock` hook and
`.github/template-sync-manifest.local.yml`; this plan builds on both.

## Goal

Today template-base marks nearly every shared file `replace`, so a sync
into template-fastapi would overwrite its own manifest, Dockerfile,
`develop.sh`, compose stack, pre-commit hooks and more. Decision
(recorded in the umbrella plan): base-owned files stay `replace` and
expose **hooks** that an instance fills with files it owns. Files with
no include mechanism of their own (JSON configs, `.pre-commit-config.yaml`
— prek has no include, verified against its docs) move to `merge`.

## Fixed names

Plans 5 and 6 build against these exact names. Don't rename anything.

| Hook | Base side (template-owned) | Instance side (instance-owned) |
|---|---|---|
| Extra devcontainer tooling | `Dockerfile` `develop` stage runs every `scripts/develop.d/*.sh` after `develop.sh` | `scripts/develop.d/NN-name.sh` |
| Extra post-create steps | `scripts/post-create.sh`, run by `devcontainer.json`'s `postCreateCommand`, runs every `scripts/post-create.d/*.sh` | `scripts/post-create.d/NN-name.sh` |
| Extra compose services / dev-service settings | `devcontainer.json` `"dockerComposeFile": ["compose.yml", "compose.instance.yml"]` | `.devcontainer/compose.instance.yml` (base ships a stub, `ignore` tier) |
| Runtime image | nothing (base `Dockerfile` is `develop`-only) | `app.Dockerfile` + `app.Dockerfile.dockerignore` |

## Approach

### 1. `scripts/develop.d/` hook

- Create `scripts/develop.d/README.md`. It should say:
  - Every `*.sh` here runs as root, in lexical filename order (use an
    `NN-` prefix, e.g. `10-apt.sh`), after `scripts/develop.sh`, during
    the `develop` stage build.
  - `PYTHON_VERSION`, `UV_VERSION` and `NODE_VERSION` are in the
    environment, and `uv`, `python3`, `node` and `prek` are already on
    `PATH`.
  - A script pins its own tool versions as
    `# renovate: datasource=... depName=...` followed on the next line
    by `NAME_VERSION=x.y.z`.
- In `Dockerfile`'s `develop` stage, directly after the existing
  `RUN bash /tmp/develop.sh ...` line, add:

      COPY scripts/develop.d/ /tmp/develop.d/
      RUN for f in /tmp/develop.d/*.sh; do [ -e "$f" ] || continue; echo "==> $f"; bash "$f" || exit 1; done

- Add a Renovate custom manager to `.github/renovate.json`, next to the
  existing `Dockerfile` one:
  - `managerFilePatterns`: `["/^scripts/develop\\.d/.*\\.sh$/", "/^scripts/post-create\\.d/.*\\.sh$/"]`
  - `matchStrings`: `["# renovate: datasource=(?<datasource>.*?) depName=(?<depName>.*?)\\s*\\n[A-Z0-9_]+_VERSION=(?<currentValue>\\S+)"]`

### 2. `scripts/post-create.d/` hook

- Create `scripts/post-create.sh` (executable, `#!/usr/bin/env bash`,
  `set -euo pipefail`). It runs:
  1. `git config --global --add safe.directory /workspace`
  2. `prek install`
  3. every `/workspace/scripts/post-create.d/*.sh`, in lexical order,
     as the current user, with the same loop shape as step 1.
- Create `scripts/post-create.d/README.md` in the same style as
  `develop.d/README.md`. Say that these scripts run as `vscode` inside
  the running devcontainer, with the compose stack up.
- In `.devcontainer/devcontainer.json`, set
  `"postCreateCommand": "bash /workspace/scripts/post-create.sh"`.

### 3. `compose.instance.yml` hook

- Create `.devcontainer/compose.instance.yml`. Its header comment says
  it's instance-owned, never touched by sync, and is where an instance
  puts `include:` stack fragments and extra `services.app` settings
  (`env_file`, `environment`, `depends_on`). Body:

      services: {}

- In `devcontainer.json`, set
  `"dockerComposeFile": ["compose.yml", "compose.instance.yml"]`.
- Verify the stub is valid:
  `docker compose -f .devcontainer/compose.yml -f .devcontainer/compose.instance.yml config`
  must exit 0 and show the `app` service. If Compose rejects
  `services: {}`, use `services:\n  app: {}` instead and re-run the
  check.
- Update the comments that still point instances at `compose.yml`'s
  own `include:`. In each, change the target to `compose.instance.yml`:
  - `.devcontainer/compose.yml`'s header comment, which says an
    instance "adds its own `include:` list here";
  - `.github/workflows/checks.yml`'s "Tear down devcontainer stack"
    comment, which says tearing down by project name "covers any
    services an instance adds through compose.yml's `include:`". Keep
    the point that no `-f` list is needed, since that still holds.

### 4. Re-tier `.github/template-sync-manifest.yml`

Overlapping patterns are an error (`template_sync_manifest.py`
`classify` rejects a path matched by more than one tier). So any
directory glob that contains a file moving to `merge` has to be replaced
by explicit per-file entries. Target state:

**`replace`** (list each path explicitly unless marked "glob"):
- `.claude/hooks/self-check.sh`, `.claude/skills/` (glob)
- `.devcontainer/compose.yml`, `.devcontainer/devcontainer-lock.json`, `.devcontainer/resolve-ssh-agent.sh`
- `.vscode/extensions.json`, `.vscode/settings.json`
- every file under `.github/workflows/` except `README.md`, listed one by one (after plan 2 there are 12)
- `.github/scripts/` (glob — nothing in it moves), `.github/ISSUE_TEMPLATE/` (glob), `.github/PULL_REQUEST_TEMPLATE.md`
- `Dockerfile`, `.gitattributes`
- `scripts/develop.sh`, `scripts/post-create.sh`, `scripts/develop.d/README.md`, `scripts/post-create.d/README.md`
- `.secrets/README.md`, `.secrets/.gitkeep`
- `CLAUDE.md`, and the `docs/*/README.md` + `docs/*/template.md` entries already there

**`merge`** (add to the existing `README.md`):
- `.claude/settings.json`, `.claude/README.md`
- `.devcontainer/devcontainer.json`, `.devcontainer/README.md`
- `.vscode/tasks.json`, `.vscode/README.md`
- `.github/workflows/README.md`, `.github/CONTENTS.md`, `.github/renovate.json`
- `.pre-commit-config.yaml`, `.mcp.json`, `.gitignore`, `.dockerignore`
- `scripts/README.md`, `docs/TEMPLATE.md`
- `.github/template-sync-manifest.yml` — **the critical fix.** Delete it
  from `replace`. As `replace`, the first sync would overwrite
  template-fastapi's own manifest, which classifies template-fastapi's
  tree for *its* downstream instances. It isn't `ignore` either:
  ordinary instances classify their own files in
  `template-sync-manifest.local.yml` (added in `v1.1.0`) and never
  edit the manifest itself, so a `merge` applies cleanly for them and
  keeps their completeness check current with base's new files. A repo
  that is itself a template edits the manifest directly and resolves
  base's additions by hand.

**`ignore`** (add to what's there; keep the existing
`.github/template-sync-manifest.local.yml` entry):
- `.devcontainer/compose.instance.yml`

Update the file's header comment:
- The paragraph starting "This is template-base's own manifest" should
  say the manifest is `merge` tier.
- The paragraph about `template-sync-manifest.local.yml` should say
  "don't edit this file; use the local file" for ordinary instances,
  and "edit this file directly" for a repo that is itself a template.

### 5. Docs

- `docs/TEMPLATE.md`: add a section "Instance extension points" holding
  the "Fixed names" table above, plus one sentence each on why
  `merge` is used for files with no include mechanism, and why the
  runtime image goes in `app.Dockerfile`. BuildKit picks up
  `app.Dockerfile.dockerignore` automatically for `-f app.Dockerfile`.
  Correct any existing sentence that tells an instance to edit
  `Dockerfile`, `develop.sh` or `compose.yml` directly.
- `docs/TEMPLATE.md` "Template sync": the local-manifest paragraph
  added in `v1.1.0` says the manifest is "`replace`-tier and would be
  overwritten". Rewrite it to match step 4's `merge` wording.
- `scripts/README.md` and `.devcontainer/README.md`: list the new files
  and link the new `docs/TEMPLATE.md` section.

## Verify

Show the output of each:

    prek run --all-files --hook-stage manual        # passes; the manifest check proves every tracked file is in exactly one tier
    docker compose -f .devcontainer/compose.yml -f .devcontainer/compose.instance.yml config >/dev/null && echo OK
    docker build --target develop -t base-develop-check .   # builds; the develop.d loop runs over zero scripts cleanly

Then test the hook with a throwaway script:

    echo 'echo HOOK-RAN' > scripts/develop.d/99-probe.sh
    docker build --target develop --no-cache --progress=plain . 2>&1 | grep HOOK-RAN
    rm scripts/develop.d/99-probe.sh

The build must print `HOOK-RAN`. Don't commit the probe.

Only the user can rebuild the devcontainer, so the `postCreateCommand`
change can't be tested live from inside it (see CLAUDE.md). Instead, run
`bash scripts/post-create.sh` in the current container and show that it
exits 0. In the PR, ask the user to rebuild and confirm.

## Done when

The PR (`feat: add instance extension points and merge (not replace)
the sync manifest`) is merged into template-base `main`. Don't
tag yet — plan 4 does that.
